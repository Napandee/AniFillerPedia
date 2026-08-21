"""Raw SQL for series_proposals — the series-level equivalent of
contributions. No "one pending per X" constraint here (#20's rule is
specific to episode contributions; a proposal targets a not-yet-existing
series, so there's no natural key two proposals could collide on beyond
title, which isn't unique — duplicate proposals get sorted out at review
time, not blocked structurally).
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def create(
    session: AsyncSession,
    *,
    title: str,
    anilist_id: int | None,
    mal_id: int | None,
    anidb_id: int | None,
    justification: str,
    submitted_by: int | None,
    license_accepted: bool,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO series_proposals
                (title, anilist_id, mal_id, anidb_id, justification,
                 submitted_by, license_accepted)
            VALUES
                (:title, :anilist_id, :mal_id, :anidb_id, :justification,
                 :submitted_by, :license_accepted)
            RETURNING *
            """
        ),
        {
            "title": title,
            "anilist_id": anilist_id,
            "mal_id": mal_id,
            "anidb_id": anidb_id,
            "justification": justification,
            "submitted_by": submitted_by,
            "license_accepted": license_accepted,
        },
    )
    return result.one()


async def list_mine(session: AsyncSession, user_id: int) -> list[Row]:
    result = await session.execute(
        text(
            """
            SELECT * FROM series_proposals
            WHERE submitted_by = :user_id
            ORDER BY submitted_at DESC
            """
        ),
        {"user_id": user_id},
    )
    return list(result.fetchall())
