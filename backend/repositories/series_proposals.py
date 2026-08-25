"""Raw SQL for series_proposals — the series-level equivalent of
contributions. No "one pending per X" constraint here (#20's rule is
specific to episode contributions; a proposal targets a not-yet-existing
series, so there's no natural key two proposals could collide on beyond
title, which isn't unique — duplicate proposals get sorted out at review
time, not blocked structurally).
"""

import json

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
    episode_data: dict | None = None,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO series_proposals
                (title, anilist_id, mal_id, anidb_id, justification,
                 submitted_by, license_accepted, episode_data)
            VALUES
                (:title, :anilist_id, :mal_id, :anidb_id, :justification,
                 :submitted_by, :license_accepted, CAST(:episode_data AS JSONB))
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
            # #85: asyncpg's JSONB binding needs an explicit JSON string,
            # not a raw dict — matches how outbox_repo.write already
            # handles its own JSONB payload column.
            "episode_data": json.dumps(episode_data) if episode_data is not None else None,
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


async def list_pending(session: AsyncSession) -> list[Row]:
    result = await session.execute(
        text("SELECT * FROM series_proposals WHERE review_status = 'pending' ORDER BY submitted_at")
    )
    return list(result.fetchall())


async def get_by_id(session: AsyncSession, proposal_id: int) -> Row | None:
    result = await session.execute(
        text("SELECT * FROM series_proposals WHERE id = :id"),
        {"id": proposal_id},
    )
    return result.first()


async def approve(session: AsyncSession, proposal_id: int, reviewed_by: int) -> Row | None:
    """Same guarded-UPDATE race protection as contributions.approve() —
    series_proposals has no resolution_method column (that's specific to
    contributions' moderator-vs-vote distinction; a proposal only ever has
    one approval path)."""
    result = await session.execute(
        text(
            """
            UPDATE series_proposals
            SET review_status = 'approved', reviewed_by = :reviewed_by, reviewed_at = now()
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": proposal_id, "reviewed_by": reviewed_by},
    )
    return result.first()


async def reject(
    session: AsyncSession, proposal_id: int, reviewed_by: int, review_note: str
) -> Row | None:
    result = await session.execute(
        text(
            """
            UPDATE series_proposals
            SET review_status = 'rejected', reviewed_by = :reviewed_by,
                reviewed_at = now(), review_note = :review_note
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": proposal_id, "reviewed_by": reviewed_by, "review_note": review_note},
    )
    return result.first()
