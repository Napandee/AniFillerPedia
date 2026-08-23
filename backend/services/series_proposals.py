from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.outbox as outbox_repo
import repositories.series as series_repo
import repositories.series_proposals as series_proposals_repo
from schemas.moderation import BulkModerationEntry, BulkModerationResult
from schemas.series_proposals import (
    SeriesProposalCreate,
    SeriesProposalOut,
    SeriesProposalReviewOut,
)

# Same transaction-boundary convention as services/contributions.py — the
# caller (router) already has `async with session.begin():` open.


async def submit_series_proposal(
    session: AsyncSession, payload: SeriesProposalCreate, current_user: Row | None
) -> SeriesProposalOut:
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

    row = await series_proposals_repo.create(
        session,
        title=payload.title,
        anilist_id=payload.anilist_id,
        mal_id=payload.mal_id,
        anidb_id=payload.anidb_id,
        justification=payload.justification,
        submitted_by=current_user.id if current_user else None,
        license_accepted=payload.license_accepted,
    )

    await outbox_repo.write(
        session,
        event_type="series_proposal.submitted",
        payload={"series_proposal_id": row.id, "title": payload.title},
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
        await series_repo.create(
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
    )
