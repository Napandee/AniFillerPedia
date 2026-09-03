from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.series as series_repo
from core.conditional import etag_for
from schemas.series import NeedsResearchItem, NeedsResearchListOut, SeriesDetailOut, SeriesListOut, SeriesOut


async def list_needs_research(session: AsyncSession, limit: int, offset: int) -> NeedsResearchListOut:
    rows, total = await series_repo.list_needs_research(session, limit, offset)
    return NeedsResearchListOut(
        items=[NeedsResearchItem(**row._mapping) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    body, _, _ = await get_series_conditional(session, identifier)
    return body


async def get_series_conditional(
    session: AsyncSession, identifier: str
) -> tuple[SeriesDetailOut, datetime, str]:
    """#155: same lookup as get_series() above, plus the derived
    last-modified timestamp + ETag the router needs to answer a
    conditional GET (If-None-Match/If-Modified-Since -> 304) without
    building the full response body. See repositories.series.
    get_last_modified for exactly which columns feed the timestamp.
    """
    row = await series_repo.get_series_by_identifier(session, identifier)
    if row is None:
        raise HTTPException(status_code=404, detail="Series not found")
    series_id = row.id
    synonyms = await series_repo.get_synonyms(session, series_id)
    related_rows = await series_repo.get_related_series(session, series_id)
    related_series = [SeriesOut(**r._mapping) for r in related_rows]

    # #133: next/previous — the nearest sequence_order above/below the
    # current series' own value, among its own series_relations group.
    # Computed here, not in the repository, since it needs both the
    # current row's sequence_order and the related_series list together.
    next_series = None
    previous_series = None
    if row.sequence_order is not None:
        ordered_candidates = sorted(
            (r for r in related_series if r.sequence_order is not None),
            key=lambda r: r.sequence_order,
        )
        greater = [r for r in ordered_candidates if r.sequence_order > row.sequence_order]
        lesser = [r for r in ordered_candidates if r.sequence_order < row.sequence_order]
        next_series = greater[0] if greater else None
        previous_series = lesser[-1] if lesser else None

    body = SeriesDetailOut(
        **row._mapping,
        synonyms=synonyms,
        related_series=related_series,
        next_series=next_series,
        previous_series=previous_series,
    )
    last_modified = await series_repo.get_last_modified(session, series_id)
    etag = etag_for(last_modified, "series", series_id)
    return body, last_modified, etag
