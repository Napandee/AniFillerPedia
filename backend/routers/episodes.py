from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

import services.episodes as episodes_service
from core.db import get_session
from schemas.contributions import ContributionHistoryEntry
from schemas.episodes import EpisodeOut

router = APIRouter(tags=["episodes"])


@router.get("/episodes/{episode_id}", response_model=EpisodeOut)
async def get_episode(
    episode_id: int, session: AsyncSession = Depends(get_session)
) -> EpisodeOut:
    return await episodes_service.get_episode(session, episode_id)


@router.get("/episodes/{episode_id}/history", response_model=list[ContributionHistoryEntry])
async def get_episode_history(
    episode_id: int, session: AsyncSession = Depends(get_session)
) -> list[ContributionHistoryEntry]:
    return await episodes_service.get_episode_history(session, episode_id)
