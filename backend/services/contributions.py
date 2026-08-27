from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.admin as admin_repo
import repositories.citations as citations_repo
import repositories.contributions as contributions_repo
import repositories.episodes as episodes_repo
import repositories.outbox as outbox_repo
import repositories.rate_limits as rate_limits_repo
import repositories.series as series_repo
import services.episode_ranges as episode_ranges
from schemas.contributions import (
    BulkContributionCreate,
    BulkContributionResult,
    BulkCreatedEntry,
    BulkSkippedEntry,
    CitationIn,
    CitationOut,
    ContributionCreate,
    ContributionOut,
    ContributionReviewOut,
    MyVoteOut,
    VoteCastOut,
)
from schemas.moderation import BulkModerationEntry, BulkModerationResult
from services.admin import compute_trust_score

# NOTE ON TRANSACTIONS: this module assumes the caller (the router) has
# already opened `async with session.begin():` — matching the convention
# established (and bug-fixed) in #8's auth router, not wrapping its own
# transaction here. See routers/contributions.py.

# #14: cumulative weighted-endorsement threshold for community-vote
# auto-promotion. 75 is a starting default, not a tuned number — CLAUDE.md
# explicitly leaves this tunable pending real contribution volume; picked
# to match the "3 endorse · trust 61/75" figure already used as the
# illustrative example in this project's own UI mockups, so the docs and
# the code start from the same number rather than two invented ones.
AUTO_APPROVAL_THRESHOLD = 75

# #84: cap on bulk-submission *calls* per account per rolling window —
# separate concern from #80's own per-batch *size* cap (2000 episodes),
# which bounds one call's blast radius but never limited how many such
# calls one account could make back-to-back. 10 per rolling 24h: #84's own
# text flags "3-5 batches in one sitting" as a legitimate pattern to leave
# headroom for; roughly doubled so a contributor correcting a mistake or
# splitting research across two sessions the same day isn't blocked by
# their own earlier good-faith submissions. Not a tuned number — same
# "no real abuse data yet" stance already taken for #14's Sybil-resistance
# question and #23's canary-detection approach; revisit once #80 has real
# usage. dry_run calls are exempt from both the check and the count — they
# write nothing, and unlimited free preview is the whole reason dry_run
# exists.
BULK_SUBMISSION_RATE_LIMIT = 10
BULK_SUBMISSION_RATE_LIMIT_WINDOW_HOURS = 24

# #139: the single-episode submission path has no #84-style per-batch size
# concern (it's always exactly one row), but was otherwise completely
# unlimited — an anonymous or authenticated caller alike could hammer this
# endpoint indefinitely. Sized more generously than the bulk limit above
# since each call here only ever creates one row (vs. up to 2000): 20 per
# rolling hour comfortably covers a real contributor working through a
# show's episodes one at a time in a sitting, while still bounding the
# storage-bloat/spam vector. Not a tuned number — same "no real abuse data
# yet" stance already taken for #84/#14; revisit if real usage disagrees.
CONTRIBUTION_SUBMIT_RATE_LIMIT = 20
CONTRIBUTION_SUBMIT_RATE_LIMIT_WINDOW_SECONDS = 60 * 60


async def submit_contribution(
    session: AsyncSession, payload: ContributionCreate, current_user: Row | None, identifier: str
) -> ContributionOut:
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

    # #139: checked before any lookup/validation work, same fail-fast
    # placement as #84's bulk check below — `identifier` is the caller's
    # own user id when authenticated or their IP otherwise (core/deps.py's
    # get_rate_limit_identifier), so a shared IP never throttles distinct
    # logged-in contributors together.
    recent_count = await rate_limits_repo.count_recent(
        session,
        scope="contribution_submit",
        identifier=identifier,
        window_seconds=CONTRIBUTION_SUBMIT_RATE_LIMIT_WINDOW_SECONDS,
    )
    if recent_count >= CONTRIBUTION_SUBMIT_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've made {recent_count} contribution submissions in the last hour "
                f"(limit {CONTRIBUTION_SUBMIT_RATE_LIMIT}). Try again later."
            ),
        )

    # #152: the target series must exist (previously unchecked here — a
    # bogus series_id would just 500 on the FK-constrained insert below),
    # and its anilist_episode_count (#49's AniList sync column), if known,
    # is what the range check right after is validated against.
    series_row = await series_repo.get_series_by_identifier(session, str(payload.series_id))
    if series_row is None:
        raise HTTPException(status_code=404, detail="Series not found")

    out_of_range = episode_ranges.find_out_of_range_episodes(
        [payload.episode_number], series_row.anilist_episode_count
    )
    if out_of_range:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"Episode {payload.episode_number} exceeds this series' known "
                    f"episode count ({series_row.anilist_episode_count})."
                ),
                "anilist_episode_count": series_row.anilist_episode_count,
            },
        )

    existing_pending = await contributions_repo.find_pending_for_episode(
        session, payload.series_id, payload.episode_number
    )
    if existing_pending is not None:
        # #20: at most one pending contribution per episode — point the
        # caller at the existing one instead of a dead-end rejection.
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A contribution for this episode is already pending review — "
                    "endorse or dispute it instead of submitting a competing one."
                ),
                "existing_contribution_id": existing_pending.id,
            },
        )

    citation_row = await citations_repo.create(
        session,
        url=payload.citation.url,
        description=payload.citation.description,
        submitted_by=current_user.id if current_user else None,
        methodology_note=payload.citation.methodology_note,
    )

    # #151: same TOCTOU gap the security review (#89) already fixed for the
    # bulk path (create_bulk_contributions_for_series below) — the
    # find_pending_for_episode check above has a real race window between
    # itself and this INSERT. Two genuinely concurrent submissions for the
    # same (series_id, episode_number) can both pass that check, then race
    # on the partial unique index here; without a savepoint + catch, the
    # loser's IntegrityError would surface as a raw 500 instead of the
    # clean 409 the frontend's isDuplicateBody handler already expects.
    try:
        async with session.begin_nested():
            contribution_row = await contributions_repo.create(
                session,
                series_id=payload.series_id,
                episode_number=payload.episode_number,
                proposed_status=payload.proposed_status,
                proposed_note=payload.proposed_note,
                citation_id=citation_row.id,
                submitted_by=current_user.id if current_user else None,
                license_accepted=payload.license_accepted,
            )
    except IntegrityError as exc:
        existing = await contributions_repo.find_pending_for_episode(
            session, payload.series_id, payload.episode_number
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A contribution for this episode is already pending review — "
                    "endorse or dispute it instead of submitting a competing one."
                ),
                "existing_contribution_id": existing.id if existing else -1,
            },
        ) from exc

    # Same transaction as the insert above (CLAUDE.md Architecture) — #9's
    # worker will pick this up once #15 registers a handler for it; until
    # then it's correctly left unprocessed, not silently dropped.
    await outbox_repo.write(
        session,
        event_type="contribution.submitted",
        payload={
            "contribution_id": contribution_row.id,
            "series_id": payload.series_id,
            "episode_number": payload.episode_number,
        },
    )

    # #139: logged once per real submission, same transaction as the
    # insert above — counts against `identifier`'s rolling-window limit
    # checked at the top of this function.
    await rate_limits_repo.record(session, scope="contribution_submit", identifier=identifier)

    return ContributionOut(
        id=contribution_row.id,
        series_id=contribution_row.series_id,
        episode_number=contribution_row.episode_number,
        proposed_status=contribution_row.proposed_status,
        proposed_note=contribution_row.proposed_note,
        citation=CitationOut(
            id=citation_row.id,
            url=citation_row.url,
            description=citation_row.description,
            source_count=citation_row.source_count,
            methodology_note=citation_row.methodology_note,
        ),
        submitted_at=contribution_row.submitted_at,
        review_status=contribution_row.review_status,
        resolution_method=contribution_row.resolution_method,
        reviewed_at=contribution_row.reviewed_at,
        review_note=contribution_row.review_note,
    )


async def _plan_bulk_contributions(
    session: AsyncSession,
    series_id: int,
    canon_ranges: str,
    mixed_ranges: str,
    filler_ranges: str,
    anilist_episode_count: int | None = None,
) -> tuple[dict[int, str], list[BulkSkippedEntry], dict[int, str]]:
    """Shared by the live dry-run preview and the real creation path below:
    parse/validate the range strings, then check #20's one-pending-per-
    episode rule BEFORE any write, so a citation row is never created for a
    batch that turns out to be entirely conflicts. Returns
    (by_episode, skipped, to_create).

    `anilist_episode_count` defaults to None (no-op validation) rather than
    being fetched in here — the router path (submit_bulk_contributions)
    already has the series row in hand and passes its
    anilist_episode_count straight through; services/series_proposals.py's
    approve_series_proposal calls create_bulk_contributions_for_series
    right after creating a brand-new series row, which never has a synced
    count yet anyway (#49 hasn't had a chance to run), so leaving it
    unpassed there is correct, not an oversight.
    """
    try:
        by_episode = episode_ranges.parse_and_validate(canon_ranges, mixed_ranges, filler_ranges)
    except episode_ranges.BulkRangeValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc

    # #152: reject any declared episode number beyond the series' own known
    # real episode count, checked before the #20 pending-conflict lookup
    # below so an out-of-range batch fails fast rather than silently
    # succeeding against episodes that can never really exist. A NULL
    # count is never validated against (see the docstring above and
    # episode_ranges.find_out_of_range_episodes).
    out_of_range = episode_ranges.find_out_of_range_episodes(by_episode.keys(), anilist_episode_count)
    if out_of_range:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"Episode number(s) {out_of_range} exceed this series' known "
                    f"episode count ({anilist_episode_count})."
                ),
                "out_of_range_episodes": out_of_range,
                "anilist_episode_count": anilist_episode_count,
            },
        )

    pending_by_episode = await contributions_repo.find_pending_for_episodes(
        session, series_id, sorted(by_episode.keys())
    )
    skipped = [
        BulkSkippedEntry(episode_number=ep, existing_contribution_id=cid)
        for ep, cid in sorted(pending_by_episode.items())
    ]
    to_create = {ep: status for ep, status in by_episode.items() if ep not in pending_by_episode}
    return by_episode, skipped, to_create


async def create_bulk_contributions_for_series(
    session: AsyncSession,
    *,
    series_id: int,
    canon_ranges: str,
    mixed_ranges: str,
    filler_ranges: str,
    citation: CitationIn,
    submitted_by: int | None,
    license_accepted: bool,
    anilist_episode_count: int | None = None,
) -> BulkContributionResult:
    """#80's real (non-dry-run) bulk-creation core, extracted for #85: reused
    both by the live POST /series/{id}/contributions/bulk endpoint below and
    by services/series_proposals.py's approve_series_proposal, which calls
    this once a proposal with attached episode data is approved and a real
    series_id exists for it to target. `submitted_by` may be None — an
    anonymous series proposal's attached episode data still needs to be
    creatable, matching #12's own anonymous-submission allowance.
    `anilist_episode_count` — see _plan_bulk_contributions's docstring for
    why it defaults to None rather than being looked up in here.
    """
    by_episode, skipped, to_create = await _plan_bulk_contributions(
        session, series_id, canon_ranges, mixed_ranges, filler_ranges, anilist_episode_count
    )

    created: list[BulkCreatedEntry] = []
    if to_create:
        citation_row = await citations_repo.create(
            session,
            url=citation.url,
            description=citation.description,
            submitted_by=submitted_by,
            methodology_note=citation.methodology_note,
        )
        for episode_number, status in sorted(to_create.items()):
            # Security review (#89): the pre-check above has a real TOCTOU
            # gap — a concurrent submission could create a pending
            # contribution for this exact episode between that check and
            # this insert. schema.sql's partial unique index is the real
            # backstop and correctly prevents a duplicate pending row, but
            # without a savepoint here the resulting IntegrityError would
            # poison this whole request's transaction, silently discarding
            # every other episode already inserted in this same batch —
            # a reliability bug, not a data-integrity one, but a bad
            # failure mode for a batch that could be hundreds of episodes.
            # A nested transaction (SAVEPOINT) scopes the rollback to just
            # this one episode on conflict.
            try:
                async with session.begin_nested():
                    contribution_row = await contributions_repo.create(
                        session,
                        series_id=series_id,
                        episode_number=episode_number,
                        proposed_status=status,
                        proposed_note=None,
                        citation_id=citation_row.id,
                        submitted_by=submitted_by,
                        license_accepted=license_accepted,
                    )
            except IntegrityError:
                existing = await contributions_repo.find_pending_for_episode(session, series_id, episode_number)
                skipped.append(
                    BulkSkippedEntry(
                        episode_number=episode_number,
                        existing_contribution_id=existing.id if existing else -1,
                    )
                )
                continue

            # Same transaction as the insert above (CLAUDE.md Architecture)
            # — identical event shape to the single-submission path, so
            # #15's outbox consumers need no changes for bulk.
            await outbox_repo.write(
                session,
                event_type="contribution.submitted",
                payload={
                    "contribution_id": contribution_row.id,
                    "series_id": series_id,
                    "episode_number": episode_number,
                },
            )
            created.append(
                BulkCreatedEntry(
                    episode_number=episode_number,
                    contribution_id=contribution_row.id,
                    proposed_status=status,
                )
            )

    return BulkContributionResult(
        dry_run=False,
        declared_count=len(by_episode),
        created=created,
        skipped_conflicts=skipped,
    )


async def submit_bulk_contributions(
    session: AsyncSession, series_id: int, payload: BulkContributionCreate, current_user: Row
) -> BulkContributionResult:
    """#80: the bulk counterpart to submit_contribution above — one shared
    citation, many per-episode contributions. Requires an authenticated
    caller (router-enforced via get_current_user, not get_current_user_
    optional) — a deliberate departure from the single-episode path's
    anonymous option, since one call here can create hundreds of rows at
    once. Every resulting contribution is otherwise indistinguishable from
    a normal single-episode submission to every downstream consumer
    (moderation queue, voting, outbox) — bulk only batches the submission,
    never the review.
    """
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

    if not payload.dry_run:
        # #84: checked before any lookup/validation work — a
        # rate-limited caller shouldn't spend this endpoint's effort
        # either, and mirrors license_accepted's own fail-fast placement
        # above.
        recent_count = await contributions_repo.count_recent_bulk_submissions(
            session, current_user.id, BULK_SUBMISSION_RATE_LIMIT_WINDOW_HOURS
        )
        if recent_count >= BULK_SUBMISSION_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You've made {recent_count} bulk submissions in the last "
                    f"{BULK_SUBMISSION_RATE_LIMIT_WINDOW_HOURS}h (limit "
                    f"{BULK_SUBMISSION_RATE_LIMIT}). Try again later — dry_run "
                    "submissions don't count against this limit if you just "
                    "want to keep validating."
                ),
            )

    series_row = await series_repo.get_series_by_identifier(session, str(series_id))
    if series_row is None:
        raise HTTPException(status_code=404, detail="Series not found")

    if payload.dry_run:
        by_episode, skipped, to_create = await _plan_bulk_contributions(
            session,
            series_id,
            payload.canon_ranges,
            payload.mixed_ranges,
            payload.filler_ranges,
            series_row.anilist_episode_count,
        )
        return BulkContributionResult(
            dry_run=True,
            declared_count=len(by_episode),
            created=[
                BulkCreatedEntry(episode_number=ep, contribution_id=None, proposed_status=status)
                for ep, status in sorted(to_create.items())
            ],
            skipped_conflicts=skipped,
        )

    result = await create_bulk_contributions_for_series(
        session,
        series_id=series_id,
        canon_ranges=payload.canon_ranges,
        mixed_ranges=payload.mixed_ranges,
        filler_ranges=payload.filler_ranges,
        citation=payload.citation,
        submitted_by=current_user.id,
        license_accepted=payload.license_accepted,
        anilist_episode_count=series_row.anilist_episode_count,
    )

    # #84: logged once per real call, same transaction as everything above
    # — regardless of how many episodes ended up created vs. skipped, this
    # was still a real (non-dry-run) call and counts against the caller's
    # rolling-window limit.
    await contributions_repo.record_bulk_submission(session, current_user.id)

    return result


async def list_pending_contributions(session: AsyncSession) -> list[ContributionOut]:
    rows = await contributions_repo.list_pending(session)
    return [
        ContributionOut(
            id=row.id,
            series_id=row.series_id,
            episode_number=row.episode_number,
            proposed_status=row.proposed_status,
            proposed_note=row.proposed_note,
            citation=CitationOut(
                id=row.citation_id, url=row.citation_url, description=row.citation_description
            ),
            submitted_at=row.submitted_at,
            review_status=row.review_status,
            resolution_method=row.resolution_method,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        for row in rows
    ]


async def _promote_to_episode_and_notify(session: AsyncSession, approved_row: Row) -> None:
    """Shared by moderator approval and #14's community-vote auto-promotion
    — both promote a resolved-approved contribution into the live episodes
    table and write the same 'contribution.approved' outbox event, in the
    same transaction as the approval itself (CLAUDE.md Architecture). The
    two paths differ only in HOW a contribution reached review_status =
    'approved' (contributions_repo.approve() vs. promote_via_vote()), never
    in what happens once it has — an auto-promoted episode must be
    indistinguishable from a moderator-approved one except via
    contributions.resolution_method (#14 acceptance criteria).
    """
    await episodes_repo.upsert(
        session,
        series_id=approved_row.series_id,
        episode_number=approved_row.episode_number,
        status=approved_row.proposed_status,
        status_note=approved_row.proposed_note,
        citation_id=approved_row.citation_id,
        approved_contribution_id=approved_row.id,
    )

    await outbox_repo.write(
        session,
        event_type="contribution.approved",
        payload={
            "contribution_id": approved_row.id,
            "series_id": approved_row.series_id,
            "episode_number": approved_row.episode_number,
        },
    )


async def approve_contribution(
    session: AsyncSession, contribution_id: int, moderator_id: int
) -> ContributionReviewOut:
    approved_row = await contributions_repo.approve(session, contribution_id, moderator_id)
    if approved_row is None:
        existing = await contributions_repo.get_by_id(session, contribution_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="contribution not found")
        raise HTTPException(
            status_code=409,
            detail=f"contribution is not pending (current status: {existing.review_status})",
        )

    await _promote_to_episode_and_notify(session, approved_row)

    return ContributionReviewOut(
        id=approved_row.id,
        review_status=approved_row.review_status,
        resolution_method=approved_row.resolution_method,
        reviewed_at=approved_row.reviewed_at,
        review_note=approved_row.review_note,
    )


async def cast_vote(
    session: AsyncSession, contribution_id: int, voter: Row, vote: str
) -> VoteCastOut:
    """#14: the community trust-weighted voting path to promotion,
    alongside moderator approval. weight_at_vote is snapshotted from the
    voter's trust_score AT VOTE TIME (schema.sql's own reasoning: later
    trust-score changes must never retroactively rewrite an already-
    resolved contribution's history) and clamped to a floor of 0 — a
    negative trust_score is meaningful at the user-record level (CLAUDE.md's
    formula lets rejections push it below zero), but a *negative-weighted*
    vote would invert its own polarity in get_net_endorsement_score's
    endorse-minus-dispute sum (a low-trust "dispute" with a negative weight
    would perversely INCREASE net_score) — clamping avoids that inversion
    without changing the trust_score formula itself.
    """
    contribution = await contributions_repo.get_by_id(session, contribution_id)
    if contribution is None:
        raise HTTPException(status_code=404, detail="contribution not found")
    if contribution.review_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"contribution is not pending (current status: {contribution.review_status})",
        )
    # Not in #14's written scope, but an obvious integrity gap left open:
    # without this, a submitter with any positive trust_score could
    # self-endorse toward the auto-approval threshold, defeating the whole
    # point of a second, independent set of eyes.
    if contribution.submitted_by is not None and contribution.submitted_by == voter.id:
        raise HTTPException(status_code=403, detail="cannot vote on your own submitted contribution")

    stats = await admin_repo.get_user_stats(session, voter.id)
    trust_score = compute_trust_score(stats.approved_count, stats.rejected_count) if stats else 0
    weight_at_vote = max(trust_score, 0)

    try:
        await contributions_repo.insert_vote(
            session,
            contribution_id=contribution_id,
            voter_id=voter.id,
            vote=vote,
            weight_at_vote=weight_at_vote,
        )
    except IntegrityError as exc:
        # schema.sql's UNIQUE (contribution_id, voter_id) — the real,
        # concurrency-safe backstop; this is what turns a raw constraint
        # violation into a clean error, same shape as #20's duplicate-
        # pending-contribution handling in submit_contribution above.
        raise HTTPException(status_code=409, detail="you have already voted on this contribution") from exc

    net_score = await contributions_repo.get_net_endorsement_score(session, contribution_id)

    if net_score >= AUTO_APPROVAL_THRESHOLD:
        promoted_row = await contributions_repo.promote_via_vote(session, contribution_id)
        # promoted_row is None if a concurrent vote already promoted this
        # contribution first (the guarded UPDATE ... WHERE review_status =
        # 'pending' pattern, same race protection as #13's approve()) —
        # this vote is still recorded either way; only ONE promotion ever
        # fires, and the re-fetch below reports the true resulting state
        # regardless of which concurrent request triggered it.
        if promoted_row is not None:
            await _promote_to_episode_and_notify(session, promoted_row)

    final_row = await contributions_repo.get_by_id(session, contribution_id)

    return VoteCastOut(
        contribution_id=contribution_id,
        vote=vote,
        weight_at_vote=weight_at_vote,
        net_score=net_score,
        auto_approval_threshold=AUTO_APPROVAL_THRESHOLD,
        review_status=final_row.review_status,
        resolution_method=final_row.resolution_method,
    )


async def reject_contribution(
    session: AsyncSession, contribution_id: int, moderator_id: int, review_note: str
) -> ContributionReviewOut:
    rejected_row = await contributions_repo.reject(session, contribution_id, moderator_id, review_note)
    if rejected_row is None:
        existing = await contributions_repo.get_by_id(session, contribution_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="contribution not found")
        raise HTTPException(
            status_code=409,
            detail=f"contribution is not pending (current status: {existing.review_status})",
        )

    await outbox_repo.write(
        session,
        event_type="contribution.rejected",
        payload={"contribution_id": rejected_row.id},
    )

    return ContributionReviewOut(
        id=rejected_row.id,
        review_status=rejected_row.review_status,
        resolution_method=rejected_row.resolution_method,
        reviewed_at=rejected_row.reviewed_at,
        review_note=rejected_row.review_note,
    )


async def _bulk_moderate(
    session: AsyncSession,
    ids: list[int],
    action: Callable[[AsyncSession, int], Awaitable[object]],
) -> BulkModerationResult:
    """#3: shared loop for bulk approve/reject — one id's failure (already
    resolved by someone else, a stale/bad id) is reported for that id
    alone, never fatal to the rest of the batch. A SAVEPOINT per id (same
    pattern as #80/#89's bulk-submission fix) means a raised HTTPException
    only rolls back that one id's own attempted writes, not anything
    already committed earlier in this same batch.
    """
    results: list[BulkModerationEntry] = []
    for item_id in ids:
        try:
            async with session.begin_nested():
                await action(session, item_id)
            results.append(BulkModerationEntry(id=item_id, ok=True))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append(BulkModerationEntry(id=item_id, ok=False, detail=detail))
    return BulkModerationResult(results=results)


async def bulk_approve_contributions(
    session: AsyncSession, ids: list[int], moderator_id: int
) -> BulkModerationResult:
    async def _approve_one(session: AsyncSession, contribution_id: int) -> None:
        await approve_contribution(session, contribution_id, moderator_id)

    return await _bulk_moderate(session, ids, _approve_one)


async def bulk_reject_contributions(
    session: AsyncSession, ids: list[int], moderator_id: int, review_note: str
) -> BulkModerationResult:
    async def _reject_one(session: AsyncSession, contribution_id: int) -> None:
        await reject_contribution(session, contribution_id, moderator_id, review_note)

    return await _bulk_moderate(session, ids, _reject_one)


async def list_my_votes(session: AsyncSession, user_id: int) -> list[MyVoteOut]:
    rows = await contributions_repo.list_votes_by_voter(session, user_id)
    return [
        MyVoteOut(
            contribution_id=row.contribution_id,
            series_id=row.series_id,
            series_title=row.series_title,
            episode_number=row.episode_number,
            proposed_status=row.proposed_status,
            vote=row.vote,
            weight_at_vote=row.weight_at_vote,
            review_status=row.review_status,
            resolution_method=row.resolution_method,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def list_my_contributions(session: AsyncSession, user_id: int) -> list[ContributionOut]:
    rows = await contributions_repo.list_mine(session, user_id)
    return [
        ContributionOut(
            id=row.id,
            series_id=row.series_id,
            episode_number=row.episode_number,
            proposed_status=row.proposed_status,
            proposed_note=row.proposed_note,
            citation=CitationOut(
                id=row.citation_id, url=row.citation_url, description=row.citation_description
            ),
            submitted_at=row.submitted_at,
            review_status=row.review_status,
            resolution_method=row.resolution_method,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        for row in rows
    ]
