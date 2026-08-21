from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import services.episodes as episodes_service
import services.series as series_service
from core.db import get_session
from schemas.episodes import EpisodeOut
from schemas.series import SeriesDetailOut, SeriesListOut

router = APIRouter(tags=["series"])


@router.get("/series", response_model=SeriesListOut)
async def list_series(
    q: str | None = Query(default=None, description="Title or synonym search"),
    anilist_id: int | None = None,
    mal_id: int | None = None,
    anidb_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SeriesListOut:
    return await series_service.search_series(
        session, q, anilist_id, mal_id, anidb_id, limit, offset
    )


@router.get("/series/{series_id}", response_model=SeriesDetailOut)
async def get_series(
    series_id: int, session: AsyncSession = Depends(get_session)
) -> SeriesDetailOut:
    return await series_service.get_series(session, series_id)


@router.get("/series/{series_id}/episodes", response_model=list[EpisodeOut])
async def list_series_episodes(
    series_id: int, session: AsyncSession = Depends(get_session)
) -> list[EpisodeOut]:
    return await episodes_service.list_episodes_for_series(session, series_id)
