from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.outbox as outbox_repo
import repositories.series_proposals as series_proposals_repo
from schemas.series_proposals import SeriesProposalCreate, SeriesProposalOut

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
