"""Raw SQL for episodes — the live, approved-only community layer.
Citation is always joined in (episodes.citation_id is NOT NULL by schema
guarantee), so callers never need a second round-trip to see the source.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT_WITH_CITATION = """
    SELECT e.id, e.series_id, e.episode_number, e.status, e.status_note,
           e.updated_at,
           c.id AS citation_id, c.url AS citation_url,
           c.description AS citation_description
    FROM episodes e
    JOIN citations c ON c.id = e.citation_id
"""


async def list_for_series(session: AsyncSession, series_id: int) -> list[Row]:
    result = await session.execute(
        text(f"{_SELECT_WITH_CITATION} WHERE e.series_id = :series_id ORDER BY e.episode_number"),
        {"series_id": series_id},
    )
    return list(result.fetchall())


async def get_by_id(session: AsyncSession, episode_id: int) -> Row | None:
    result = await session.execute(
        text(f"{_SELECT_WITH_CITATION} WHERE e.id = :id"),
        {"id": episode_id},
    )
    return result.first()
