from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

import services.episodes as episodes_service
from core.db import get_session
from schemas.contributions import ContributionHistoryEntry
from schemas.episodes import EpisodeOut
from schemas.errors import ErrorDetail

router = APIRouter(tags=["episodes"])

_EPISODE_NOT_FOUND = {404: {"model": ErrorDetail, "description": "No episode matches this id"}}


@router.get("/episodes/{episode_id}", response_model=EpisodeOut, responses=_EPISODE_NOT_FOUND)
async def get_episode(
    episode_id: int, session: AsyncSession = Depends(get_session)
) -> EpisodeOut:
    """Public, unauthenticated. Same shape as one entry from
    `GET /series/{id}/episodes` — the current, live-authoritative status
    for this episode, not its history (see the /history route below).
    """
    return await episodes_service.get_episode(session, episode_id)


@router.get(
    "/episodes/{episode_id}/history",
    response_model=list[ContributionHistoryEntry],
    responses=_EPISODE_NOT_FOUND,
)
async def get_episode_history(
    episode_id: int, session: AsyncSession = Depends(get_session)
) -> list[ContributionHistoryEntry]:
    """Every contribution ever submitted for this episode — not just the
    current live one — including each one's review outcome and any
    community votes cast on it. Public, unauthenticated: this project
    doesn't anonymize active contributors, only accounts that have been
    deleted (see the privacy policy).
    """
    return await episodes_service.get_episode_history(session, episode_id)
