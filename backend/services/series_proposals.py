from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.contributions as contributions_repo
import repositories.outbox as outbox_repo
import repositories.rate_limits as rate_limits_repo
import repositories.series as series_repo
import repositories.series_proposals as series_proposals_repo
import services.contributions as contributions_service
import services.episode_ranges as episode_ranges
from schemas.contributions import CitationIn
from schemas.moderation import BulkModerationEntry, BulkModerationResult
from schemas.series_proposals import (
    EpisodeDataOut,
    SeriesProposalCreate,
    SeriesProposalOut,
    SeriesProposalReviewOut,
)

# Same transaction-boundary convention as services/contributions.py — the
# caller (router) already has `async with session.begin():` open.

# #139: this proposal endpoint's episode_data field is structurally
# identical in blast radius to services/contributions.py's own bulk-
# contribution endpoint (up to 2000 episodes per call, validated against
# the same episode_ranges cap) but never called that endpoint's #84 rate
# limiter at all — confirmed via grep as the actual security-review
# finding. Scope name for the anonymous-caller counter below.
ANONYMOUS_EPISODE_DATA_RATE_LIMIT_SCOPE = "series_proposal_bulk_anonymous"


async def submit_series_proposal(
    session: AsyncSession, payload: SeriesProposalCreate, current_user: Row | None, identifier: str
) -> SeriesProposalOut:
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

    episode_data_dict: dict | None = None
    if payload.episode_data is not None:
        # #139: apply #84's own bulk-submission rate limit here too, since
        # this field carries the identical up-to-2000-episode blast radius
        # as the direct bulk-contribution endpoint. An authenticated caller
        # is counted against the SAME bulk_submission_events account-keyed
        # counter #84 already built (hitting either endpoint consumes the
        # same shared budget) — reusing it directly rather than inventing
        # a parallel per-account mechanism, per this issue's own guidance.
        # An anonymous caller has no account for that table's NOT NULL
        # submitted_by FK to key on, so falls back to a parallel IP-keyed
        # counter (repositories/rate_limits.py) using the identical
        # constants, since the size/frequency concern is the same either
        # way.
        if current_user is not None:
            recent_count = await contributions_repo.count_recent_bulk_submissions(
                session, current_user.id, contributions_service.BULK_SUBMISSION_RATE_LIMIT_WINDOW_HOURS
            )
        else:
            recent_count = await rate_limits_repo.count_recent(
                session,
                scope=ANONYMOUS_EPISODE_DATA_RATE_LIMIT_SCOPE,
                identifier=identifier,
                window_seconds=contributions_service.BULK_SUBMISSION_RATE_LIMIT_WINDOW_HOURS * 3600,
            )
        if recent_count >= contributions_service.BULK_SUBMISSION_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You've made {recent_count} bulk-episode-data submissions in the last "
                    f"{contributions_service.BULK_SUBMISSION_RATE_LIMIT_WINDOW_HOURS}h (limit "
                    f"{contributions_service.BULK_SUBMISSION_RATE_LIMIT}, shared with "
                    "POST /series/<id>/contributions/bulk). Try again later, or submit this "
                    "proposal without attached episode data."
                ),
            )

        # #85: validate ranges at submission time, not deferred to
        # approval — a contributor gets feedback on a malformed range
        # right away, rather than a moderator discovering it's unusable
        # much later. Raises the same 422 shape #80's bulk endpoint does.
        try:
            episode_ranges.parse_and_validate(
                payload.episode_data.canon_ranges,
                payload.episode_data.mixed_ranges,
                payload.episode_data.filler_ranges,
            )
        except episode_ranges.BulkRangeValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        episode_data_dict = payload.episode_data.model_dump()

    row = await series_proposals_repo.create(
        session,
        title=payload.title,
        anilist_id=payload.anilist_id,
        mal_id=payload.mal_id,
        anidb_id=payload.anidb_id,
        justification=payload.justification,
        submitted_by=current_user.id if current_user else None,
        license_accepted=payload.license_accepted,
        episode_data=episode_data_dict,
    )

    await outbox_repo.write(
        session,
        event_type="series_proposal.submitted",
        payload={"series_proposal_id": row.id, "title": payload.title},
    )

    if payload.episode_data is not None:
        # #139: logged once per real call with attached episode data, same
        # transaction as everything above — counts against the same
        # rolling-window limit checked above (shared with the direct bulk
        # endpoint for authenticated callers).
        if current_user is not None:
            await contributions_repo.record_bulk_submission(session, current_user.id)
        else:
            await rate_limits_repo.record(
                session, scope=ANONYMOUS_EPISODE_DATA_RATE_LIMIT_SCOPE, identifier=identifier
            )

    return _row_to_out(row)


async def list_my_series_proposals(session: AsyncSession, user_id: int) -> list[SeriesProposalOut]:
    rows = await series_proposals_repo.list_mine(session, user_id)
    return [_row_to_out(row) for row in rows]


async def list_pending_series_proposals(session: AsyncSession) -> list[SeriesProposalOut]:
    rows = await series_proposals_repo.list_pending(session)
    return [_row_to_out(row) for row in rows]


async def approve_series_proposal(
    session: AsyncSession, series_proposal_id: int, moderator_id: int
) -> SeriesProposalReviewOut:
    approved_row = await series_proposals_repo.approve(session, series_proposal_id, moderator_id)
    if approved_row is None:
        existing = await series_proposals_repo.get_by_id(session, series_proposal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="series proposal not found")
        raise HTTPException(
            status_code=409,
            detail=f"series proposal is not pending (current status: {existing.review_status})",
        )

    # Promote into the live series catalog — same transaction as the
    # approval itself. anilist_id/mal_id/anidb_id are UNIQUE but nullable;
    # a collision with an already-bootstrapped series raises IntegrityError
    # here, which we turn into a clean 409 rather than a raw 500.
    try:
        new_series_row = await series_repo.create(
            session,
            title=approved_row.title,
            anilist_id=approved_row.anilist_id,
            mal_id=approved_row.mal_id,
            anidb_id=approved_row.anidb_id,
            provenance="community",
            added_by=moderator_id,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="a series with one of these external IDs already exists",
        ) from exc

    # #85: a proposal submitted with attached episode-range data creates
    # its bulk contributions in this same step/transaction, targeting the
    # series row just created above — reuses #80's own validation/creation
    # core (services/contributions.py) rather than reimplementing it.
    # submitted_by/license_accepted come from the ORIGINAL proposal, not
    # the approving moderator — the moderator is approving the proposal,
    # not authoring the episode data themselves.
    episode_contributions_created: int | None = None
    if approved_row.episode_data is not None:
        ed = approved_row.episode_data
        bulk_result = await contributions_service.create_bulk_contributions_for_series(
            session,
            series_id=new_series_row.id,
            canon_ranges=ed.get("canon_ranges", ""),
            mixed_ranges=ed.get("mixed_ranges", ""),
            filler_ranges=ed.get("filler_ranges", ""),
            citation=CitationIn(**ed["citation"]),
            submitted_by=approved_row.submitted_by,
            license_accepted=approved_row.license_accepted,
        )
        episode_contributions_created = len(bulk_result.created)

    await outbox_repo.write(
        session,
        event_type="series_proposal.approved",
        payload={"series_proposal_id": approved_row.id, "title": approved_row.title},
    )

    return SeriesProposalReviewOut(
        id=approved_row.id,
        review_status=approved_row.review_status,
        reviewed_at=approved_row.reviewed_at,
        review_note=approved_row.review_note,
        episode_contributions_created=episode_contributions_created,
    )


async def reject_series_proposal(
    session: AsyncSession, series_proposal_id: int, moderator_id: int, review_note: str
) -> SeriesProposalReviewOut:
    rejected_row = await series_proposals_repo.reject(session, series_proposal_id, moderator_id, review_note)
    if rejected_row is None:
        existing = await series_proposals_repo.get_by_id(session, series_proposal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="series proposal not found")
        raise HTTPException(
            status_code=409,
            detail=f"series proposal is not pending (current status: {existing.review_status})",
        )

    await outbox_repo.write(
        session,
        event_type="series_proposal.rejected",
        payload={"series_proposal_id": rejected_row.id},
    )

    return SeriesProposalReviewOut(
        id=rejected_row.id,
        review_status=rejected_row.review_status,
        reviewed_at=rejected_row.reviewed_at,
        review_note=rejected_row.review_note,
    )


async def bulk_approve_series_proposals(
    session: AsyncSession, ids: list[int], moderator_id: int
) -> BulkModerationResult:
    """#3: same per-id-savepoint pattern as services/contributions.py's
    bulk_approve_contributions — one id already resolved by someone else
    (or a bad id) is reported for that id alone, never fatal to the rest.
    """
    results: list[BulkModerationEntry] = []
    for proposal_id in ids:
        try:
            async with session.begin_nested():
                await approve_series_proposal(session, proposal_id, moderator_id)
            results.append(BulkModerationEntry(id=proposal_id, ok=True))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append(BulkModerationEntry(id=proposal_id, ok=False, detail=detail))
    return BulkModerationResult(results=results)


async def bulk_reject_series_proposals(
    session: AsyncSession, ids: list[int], moderator_id: int, review_note: str
) -> BulkModerationResult:
    results: list[BulkModerationEntry] = []
    for proposal_id in ids:
        try:
            async with session.begin_nested():
                await reject_series_proposal(session, proposal_id, moderator_id, review_note)
            results.append(BulkModerationEntry(id=proposal_id, ok=True))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append(BulkModerationEntry(id=proposal_id, ok=False, detail=detail))
    return BulkModerationResult(results=results)


def _row_to_out(row: Row) -> SeriesProposalOut:
    return SeriesProposalOut(
        id=row.id,
        title=row.title,
        anilist_id=row.anilist_id,
        mal_id=row.mal_id,
        anidb_id=row.anidb_id,
        justification=row.justification,
        submitted_at=row.submitted_at,
        review_status=row.review_status,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
        episode_data=_episode_data_out(row.episode_data),
    )


def _episode_data_out(episode_data: dict | None) -> EpisodeDataOut | None:
    if episode_data is None:
        return None
    # Defensive, not assumed: these ranges were already validated at
    # submission time (submit_series_proposal), so this should never raise
    # — but one malformed row re-raising here would take down the whole
    # list/moderation-queue endpoint for every OTHER proposal too, which is
    # a worse failure mode than showing 0 for this one row's count.
    try:
        by_episode = episode_ranges.parse_and_validate(
            episode_data.get("canon_ranges", ""),
            episode_data.get("mixed_ranges", ""),
            episode_data.get("filler_ranges", ""),
        )
        declared_count = len(by_episode)
    except episode_ranges.BulkRangeValidationError:
        declared_count = 0
    return EpisodeDataOut(
        canon_ranges=episode_data.get("canon_ranges", ""),
        mixed_ranges=episode_data.get("mixed_ranges", ""),
        filler_ranges=episode_data.get("filler_ranges", ""),
        citation=CitationIn(**episode_data["citation"]),
        declared_count=declared_count,
    )
