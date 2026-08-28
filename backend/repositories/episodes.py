"""Raw SQL for episodes — the live, approved-only community layer.
Citation is always joined in (episodes.citation_id is NOT NULL by schema
guarantee), so callers never need a second round-trip to see the source.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT_WITH_CITATION = """
    SELECT e.id, e.series_id, e.episode_number, e.status, e.status_note,
           e.title, e.updated_at,
           c.id AS citation_id, c.url AS citation_url,
           c.description AS citation_description, c.source_count AS citation_source_count,
           c.methodology_note AS citation_methodology_note,
           ses.aired_at,
           (pc.id IS NOT NULL) AS has_pending_contribution
    FROM episodes e
    JOIN citations c ON c.id = e.citation_id
    LEFT JOIN series_episode_schedule ses
        ON ses.series_id = e.series_id AND ses.episode_number = e.episode_number
    -- #87: at most one match per episode — schema.sql's own
    -- contributions_one_pending_per_episode partial unique index
    -- (series_id, episode_number) WHERE review_status = 'pending' is
    -- exactly this join condition, so this is an indexed lookup per row,
    -- not a table scan, even on a 1000+ episode show.
    LEFT JOIN contributions pc
        ON pc.series_id = e.series_id AND pc.episode_number = e.episode_number
        AND pc.review_status = 'pending'
"""


async def list_for_series(session: AsyncSession, series_id: int) -> list[Row]:
    result = await session.execute(
        text(f"{_SELECT_WITH_CITATION} WHERE e.series_id = :series_id ORDER BY e.episode_number"),
        {"series_id": series_id},
    )
    return list(result.fetchall())


async def get_max_updated_at(session: AsyncSession, series_id: int) -> Row | None:
    """#155: conditional-request support for GET /series/{id}/episodes.
    episodes.updated_at is bumped by upsert() below on every contribution
    approval that changes an episode's status/title/citation — exactly
    "the episodes list changed" for this endpoint's own payload (status,
    status_note, title, citation, has_pending_contribution all come from
    joins keyed off this same row). aired_at (series_episode_schedule) is
    NOT included: it's a separate, lower-signal sync table (#49) that
    doesn't drive any of the filler/canon content this project's ETag is
    meant to let a consumer skip re-fetching — see the caller in
    services/episodes.py for how the series-has-zero-episodes case (NULL
    here) is handled.
    """
    result = await session.execute(
        text("SELECT MAX(updated_at) AS max_updated_at FROM episodes WHERE series_id = :series_id"),
        {"series_id": series_id},
    )
    return result.one()


async def get_by_id(session: AsyncSession, episode_id: int) -> Row | None:
    result = await session.execute(
        text(f"{_SELECT_WITH_CITATION} WHERE e.id = :id"),
        {"id": episode_id},
    )
    return result.first()


async def upsert(
    session: AsyncSession,
    *,
    series_id: int,
    episode_number: int,
    status: str,
    status_note: str | None,
    citation_id: int,
    approved_contribution_id: int,
) -> Row:
    """#13: promote an approved contribution into the live episodes table.
    ON CONFLICT (series_id, episode_number) — schema.sql's own UNIQUE
    constraint — so a later contribution correcting an already-approved
    episode overwrites it rather than erroring; full history stays in
    contributions regardless (episodes only ever reflects the current
    approved state, per CLAUDE.md Architecture).
    """
    result = await session.execute(
        text(
            """
            INSERT INTO episodes
                (series_id, episode_number, status, status_note, citation_id, approved_contribution_id)
            VALUES
                (:series_id, :episode_number, :status, :status_note, :citation_id, :approved_contribution_id)
            ON CONFLICT (series_id, episode_number) DO UPDATE SET
                status = EXCLUDED.status,
                status_note = EXCLUDED.status_note,
                citation_id = EXCLUDED.citation_id,
                approved_contribution_id = EXCLUDED.approved_contribution_id,
                updated_at = now()
            RETURNING *
            """
        ),
        {
            "series_id": series_id,
            "episode_number": episode_number,
            "status": status,
            "status_note": status_note,
            "citation_id": citation_id,
            "approved_contribution_id": approved_contribution_id,
        },
    )
    return result.one()
