"""Raw SQL for the series catalog. Search matches title AND series_synonyms
— the whole reason #4 captured synonyms during the one-shot bootstrap
import was so search could match alternate/native-script titles, not just
the canonical one (CLAUDE.md Decisions Made).
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def search_series(
    session: AsyncSession,
    q: str | None,
    anilist_id: int | None,
    mal_id: int | None,
    anidb_id: int | None,
    limit: int,
    offset: int,
) -> tuple[list[Row], int]:
    where = []
    params: dict = {"limit": limit, "offset": offset}

    if q:
        where.append(
            "(s.title ILIKE :q OR EXISTS ("
            "SELECT 1 FROM series_synonyms syn "
            "WHERE syn.series_id = s.id AND syn.synonym ILIKE :q))"
        )
        params["q"] = f"%{q}%"
    if anilist_id is not None:
        where.append("s.anilist_id = :anilist_id")
        params["anilist_id"] = anilist_id
    if mal_id is not None:
        where.append("s.mal_id = :mal_id")
        params["mal_id"] = mal_id
    if anidb_id is not None:
        where.append("s.anidb_id = :anidb_id")
        params["anidb_id"] = anidb_id

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = (
        await session.execute(
            text(f"SELECT count(*) FROM series s {where_sql}"), params
        )
    ).scalar_one()

    rows = (
        await session.execute(
            text(
                f"""
                SELECT s.id, s.anilist_id, s.mal_id, s.anidb_id, s.title,
                       s.provenance, s.created_at
                FROM series s
                {where_sql}
                ORDER BY s.id
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()

    return list(rows), total


async def get_series_by_id(session: AsyncSession, series_id: int) -> Row | None:
    result = await session.execute(
        text(
            "SELECT id, anilist_id, mal_id, anidb_id, title, provenance, created_at "
            "FROM series WHERE id = :id"
        ),
        {"id": series_id},
    )
    return result.first()


async def get_synonyms(session: AsyncSession, series_id: int) -> list[str]:
    result = await session.execute(
        text("SELECT synonym FROM series_synonyms WHERE series_id = :id ORDER BY id"),
        {"id": series_id},
    )
    return [row.synonym for row in result.fetchall()]


async def create(
    session: AsyncSession,
    *,
    title: str,
    anilist_id: int | None,
    mal_id: int | None,
    anidb_id: int | None,
    provenance: str,
    added_by: int | None,
) -> Row:
    """#13: promote an approved series_proposal into the live series
    catalog. anilist_id/mal_id/anidb_id are UNIQUE but nullable — a
    proposal whose external ID collides with an already-bootstrapped
    series raises IntegrityError, which the service layer (not this
    repository) turns into a clean 409 rather than a raw 500.
    """
    result = await session.execute(
        text(
            """
            INSERT INTO series (title, anilist_id, mal_id, anidb_id, provenance, added_by)
            VALUES (:title, :anilist_id, :mal_id, :anidb_id, :provenance, :added_by)
            RETURNING *
            """
        ),
        {
            "title": title,
            "anilist_id": anilist_id,
            "mal_id": mal_id,
            "anidb_id": anidb_id,
            "provenance": provenance,
            "added_by": added_by,
        },
    )
    return result.one()
