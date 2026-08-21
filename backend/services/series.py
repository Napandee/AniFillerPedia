from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.series as series_repo
from schemas.series import SeriesDetailOut, SeriesListOut, SeriesOut


async def search_series(
    session: AsyncSession,
    q: str | None,
    anilist_id: int | None,
    mal_id: int | None,
    anidb_id: int | None,
    limit: int,
    offset: int,
) -> SeriesListOut:
    rows, total = await series_repo.search_series(
        session, q, anilist_id, mal_id, anidb_id, limit, offset
    )
    return SeriesListOut(
        items=[SeriesOut(**row._mapping) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_series(session: AsyncSession, series_id: int) -> SeriesDetailOut:
    row = await series_repo.get_series_by_id(session, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Series not found")
    synonyms = await series_repo.get_synonyms(session, series_id)
    return SeriesDetailOut(**row._mapping, synonyms=synonyms)
