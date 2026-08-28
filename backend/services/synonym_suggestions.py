"""#148 — a contributor's suggestion to add a synonym (alternate/dub/
regional title) to an already-catalogued series.

SCOPE DECISION (see the issue for the two options it framed): a small,
dedicated series_synonym_suggestions table + moderator-only approval,
NOT an extension of series_proposals.

Why not extend series_proposals: that flow is scoped to "a title that
doesn't exist in the catalog yet" — every column (anilist_id/mal_id/
anidb_id, the #150 duplicate-title-similarity check, #85's attached
episode_data) exists to support *creating a new series row*. Adding a
`target_series_id`-style branch would mean threading a second, unrelated
code path through approve_series_proposal, which already juggles two
real pieces of complexity (episode_data promotion, duplicate detection)
— growing that function's branching for a feature that shares almost
none of its actual logic (no episode data, no new series row, no
duplicate-series check) isn't a simplification, it's coupling two
different moderation units because they happen to both start as
"pending review."

Why not contributions: that table is episode-status-shaped
(episode_number + proposed_status + citation_id NOT NULL) — a synonym
isn't an episode claim and doesn't need a full CitationIn citation
object the way a filler/canon determination does.

Why moderator-only, not #14's trust-weighted voting: a synonym
suggestion is a single low-blast-radius string that doesn't touch
episode status or citations — approving one takes a moderator seconds
(does this title actually belong to this series?), and there's no
real "cross-referenced evidence" dimension for a community vote to
usefully weigh the way there is for a disputed filler/canon call.
Building out contribution_votes-shaped machinery (weight_at_vote
snapshotting, net-score threshold, self-vote guard) for this would be
disproportionate — moderator approval, always available, is enough.

Anonymous submission is allowed (same CLAUDE.md precedent as
contributions/series_proposals) — Turnstile-gated, license_accepted
required, same structural pattern as everywhere else in this project.
"""

from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.outbox as outbox_repo
import repositories.rate_limits as rate_limits_repo
import repositories.series as series_repo
import repositories.synonym_suggestions as synonym_suggestions_repo
from schemas.moderation import BulkModerationEntry, BulkModerationResult
from schemas.synonym_suggestions import (
    SynonymSuggestionCreate,
    SynonymSuggestionOut,
    SynonymSuggestionReviewOut,
)

# Same rolling-window shape as #139's CONTRIBUTION_SUBMIT_RATE_LIMIT
# (services/contributions.py) — a synonym suggestion is, if anything, an
# even smaller single-row write than a contribution, so it gets the same
# generous-but-bounded budget rather than a stricter one invented for no
# reason. Its own scope name keeps the counter independent of every other
# endpoint's budget (repositories/rate_limits.py).
SYNONYM_SUGGESTION_SUBMIT_RATE_LIMIT = 20
SYNONYM_SUGGESTION_SUBMIT_RATE_LIMIT_WINDOW_SECONDS = 60 * 60


async def submit_synonym_suggestion(
    session: AsyncSession, payload: SynonymSuggestionCreate, current_user: Row | None, identifier: str
) -> SynonymSuggestionOut:
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

    recent_count = await rate_limits_repo.count_recent(
        session,
        scope="synonym_suggestion_submit",
        identifier=identifier,
        window_seconds=SYNONYM_SUGGESTION_SUBMIT_RATE_LIMIT_WINDOW_SECONDS,
    )
    if recent_count >= SYNONYM_SUGGESTION_SUBMIT_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've made {recent_count} synonym suggestions in the last hour "
                f"(limit {SYNONYM_SUGGESTION_SUBMIT_RATE_LIMIT}). Try again later."
            ),
        )

    series_row = await series_repo.get_series_by_identifier(session, str(payload.series_id))
    if series_row is None:
        raise HTTPException(status_code=404, detail="Series not found")

    synonym = payload.synonym.strip()
    if not synonym:
        raise HTTPException(status_code=422, detail="synonym must not be blank")

    existing_synonyms = await series_repo.get_synonyms(session, payload.series_id)
    if synonym in existing_synonyms:
        raise HTTPException(
            status_code=409,
            detail=f'"{synonym}" is already a known synonym for this series.',
        )

    existing_pending = await synonym_suggestions_repo.find_pending_for_target(
        session, payload.series_id, synonym
    )
    if existing_pending is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A suggestion for this exact synonym is already pending review for this "
                    "series."
                ),
                "existing_suggestion_id": existing_pending.id,
            },
        )

    # Same TOCTOU-closing SAVEPOINT pattern as submit_contribution
    # (services/contributions.py) — the pending-check above has a real
    # race window against a genuinely concurrent identical submission,
    # closed by the partial unique index (migrations/016) plus catching
    # its IntegrityError here rather than letting it surface as a raw 500.
    try:
        async with session.begin_nested():
            suggestion_row = await synonym_suggestions_repo.create(
                session,
                series_id=payload.series_id,
                synonym=synonym,
                note=payload.note,
                submitted_by=current_user.id if current_user else None,
                license_accepted=payload.license_accepted,
            )
    except IntegrityError as exc:
        existing = await synonym_suggestions_repo.find_pending_for_target(
            session, payload.series_id, synonym
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A suggestion for this exact synonym is already pending review for this "
                    "series."
                ),
                "existing_suggestion_id": existing.id if existing else -1,
            },
        ) from exc

    await outbox_repo.write(
        session,
        event_type="synonym_suggestion.submitted",
        payload={"synonym_suggestion_id": suggestion_row.id, "series_id": payload.series_id},
    )

    await rate_limits_repo.record(session, scope="synonym_suggestion_submit", identifier=identifier)

    return SynonymSuggestionOut(
        id=suggestion_row.id,
        series_id=suggestion_row.series_id,
        series_title=series_row.title,
        series_slug=series_row.slug,
        synonym=suggestion_row.synonym,
        note=suggestion_row.note,
        submitted_at=suggestion_row.submitted_at,
        review_status=suggestion_row.review_status,
        reviewed_at=suggestion_row.reviewed_at,
        review_note=suggestion_row.review_note,
    )


async def list_pending_synonym_suggestions(session: AsyncSession) -> list[SynonymSuggestionOut]:
    rows = await synonym_suggestions_repo.list_pending(session)
    return [
        SynonymSuggestionOut(
            id=row.id,
            series_id=row.series_id,
            series_title=row.series_title,
            series_slug=row.series_slug,
            synonym=row.synonym,
            note=row.note,
            submitted_at=row.submitted_at,
            review_status=row.review_status,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        for row in rows
    ]


async def list_my_synonym_suggestions(session: AsyncSession, user_id: int) -> list[SynonymSuggestionOut]:
    rows = await synonym_suggestions_repo.list_mine(session, user_id)
    return [
        SynonymSuggestionOut(
            id=row.id,
            series_id=row.series_id,
            synonym=row.synonym,
            note=row.note,
            submitted_at=row.submitted_at,
            review_status=row.review_status,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        for row in rows
    ]


async def approve_synonym_suggestion(
    session: AsyncSession, suggestion_id: int, moderator_id: int
) -> SynonymSuggestionReviewOut:
    approved_row = await synonym_suggestions_repo.approve(session, suggestion_id, moderator_id)
    if approved_row is None:
        existing = await synonym_suggestions_repo.get_by_id(session, suggestion_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="synonym suggestion not found")
        raise HTTPException(
            status_code=409,
            detail=f"synonym suggestion is not pending (current status: {existing.review_status})",
        )

    # The real write into series_synonyms — same transaction as the
    # approval itself (CLAUDE.md Architecture). series_synonyms.UNIQUE
    # (series_id, synonym) is the real backstop against a duplicate that
    # slipped past the pre-submission check above (e.g. two suggestions
    # for the identical synonym both got approved in quick succession, or
    # this synonym was captured at bootstrap time after this suggestion
    # was already pending) — turned into a clean 409 rather than a raw
    # 500, same precedent as approve_series_proposal's anilist_id
    # collision handling.
    try:
        async with session.begin_nested():
            await series_repo.add_synonym(session, approved_row.series_id, approved_row.synonym)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="this series already has that exact synonym recorded",
        ) from exc

    await outbox_repo.write(
        session,
        event_type="synonym_suggestion.approved",
        payload={"synonym_suggestion_id": approved_row.id, "series_id": approved_row.series_id},
    )

    return SynonymSuggestionReviewOut(
        id=approved_row.id,
        review_status=approved_row.review_status,
        reviewed_at=approved_row.reviewed_at,
        review_note=approved_row.review_note,
    )


async def reject_synonym_suggestion(
    session: AsyncSession, suggestion_id: int, moderator_id: int, review_note: str
) -> SynonymSuggestionReviewOut:
    rejected_row = await synonym_suggestions_repo.reject(session, suggestion_id, moderator_id, review_note)
    if rejected_row is None:
        existing = await synonym_suggestions_repo.get_by_id(session, suggestion_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="synonym suggestion not found")
        raise HTTPException(
            status_code=409,
            detail=f"synonym suggestion is not pending (current status: {existing.review_status})",
        )

    await outbox_repo.write(
        session,
        event_type="synonym_suggestion.rejected",
        payload={"synonym_suggestion_id": rejected_row.id},
    )

    return SynonymSuggestionReviewOut(
        id=rejected_row.id,
        review_status=rejected_row.review_status,
        reviewed_at=rejected_row.reviewed_at,
        review_note=rejected_row.review_note,
    )


async def bulk_approve_synonym_suggestions(
    session: AsyncSession, ids: list[int], moderator_id: int
) -> BulkModerationResult:
    """#3-style shared-savepoint bulk loop, mirrored here for parity with
    the contributions/series-proposals moderation queues — see
    services/contributions.py's _bulk_moderate for the identical pattern
    this hand-rolls (kept local rather than importing that private helper
    across modules)."""
    results: list[BulkModerationEntry] = []
    for suggestion_id in ids:
        try:
            async with session.begin_nested():
                await approve_synonym_suggestion(session, suggestion_id, moderator_id)
            results.append(BulkModerationEntry(id=suggestion_id, ok=True))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append(BulkModerationEntry(id=suggestion_id, ok=False, detail=detail))
    return BulkModerationResult(results=results)


async def bulk_reject_synonym_suggestions(
    session: AsyncSession, ids: list[int], moderator_id: int, review_note: str
) -> BulkModerationResult:
    results: list[BulkModerationEntry] = []
    for suggestion_id in ids:
        try:
            async with session.begin_nested():
                await reject_synonym_suggestion(session, suggestion_id, moderator_id, review_note)
            results.append(BulkModerationEntry(id=suggestion_id, ok=True))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append(BulkModerationEntry(id=suggestion_id, ok=False, detail=detail))
    return BulkModerationResult(results=results)
