from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import services.series_proposals as series_proposals_service
import services.turnstile as turnstile_service
from core.db import get_session
from core.deps import get_current_user, get_current_user_optional
from schemas.series_proposals import SeriesProposalCreate, SeriesProposalOut

router = APIRouter(tags=["series-proposals"])


@router.post("/series-proposals", response_model=SeriesProposalOut, status_code=201)
async def submit_series_proposal(
    payload: SeriesProposalCreate,
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalOut:
    if current_user is None:
        allowed = await turnstile_service.verify(payload.turnstile_token)
        if not allowed:
            raise HTTPException(status_code=422, detail="Turnstile verification failed")

    # Not a context-managed session.begin() — see the detailed comment in
    # routers/contributions.py's identical fix. Same root cause: the
    # get_current_user_optional dependency's SELECT autobegins a
    # transaction before this handler body runs.
    result = await series_proposals_service.submit_series_proposal(session, payload, current_user)
    await session.commit()
    return result


@router.get("/series-proposals/mine", response_model=list[SeriesProposalOut])
async def my_series_proposals(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[SeriesProposalOut]:
    return await series_proposals_service.list_my_series_proposals(session, current_user.id)
