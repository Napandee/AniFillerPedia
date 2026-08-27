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
    sort: str | None = None,
) -> SeriesListOut:
    rows, total = await series_repo.search_series(
        session, q, anilist_id, mal_id, anidb_id, limit, offset, sort
    )
    return SeriesListOut(
        items=[SeriesOut(**row._mapping) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_series(session: AsyncSession, identifier: str) -> SeriesDetailOut:
    """#116: `identifier` is either a numeric series id or a slug — see
    repositories.series.get_series_by_identifier for how that's resolved.
    """
    row = await series_repo.get_series_by_identifier(session, identifier)
    if row is None:
        raise HTTPException(status_code=404, detail="Series not found")
    series_id = row.id
    synonyms = await series_repo.get_synonyms(session, series_id)
    related_rows = await series_repo.get_related_series(session, series_id)
    related_series = [SeriesOut(**r._mapping) for r in related_rows]
    return SeriesDetailOut(**row._mapping, synonyms=synonyms, related_series=related_series)
