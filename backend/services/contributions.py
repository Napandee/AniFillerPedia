from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.admin as admin_repo
import repositories.citations as citations_repo
import repositories.contributions as contributions_repo
import repositories.episodes as episodes_repo
import repositories.outbox as outbox_repo
from schemas.contributions import (
    CitationOut,
    ContributionCreate,
    ContributionOut,
    ContributionReviewOut,
    VoteCastOut,
)
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


async def submit_contribution(
    session: AsyncSession, payload: ContributionCreate, current_user: Row | None
) -> ContributionOut:
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

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
    )

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

    return ContributionOut(
        id=contribution_row.id,
        series_id=contribution_row.series_id,
        episode_number=contribution_row.episode_number,
        proposed_status=contribution_row.proposed_status,
        proposed_note=contribution_row.proposed_note,
        citation=CitationOut(
            id=citation_row.id, url=citation_row.url, description=citation_row.description
        ),
        submitted_at=contribution_row.submitted_at,
        review_status=contribution_row.review_status,
        resolution_method=contribution_row.resolution_method,
        reviewed_at=contribution_row.reviewed_at,
        review_note=contribution_row.review_note,
    )


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
