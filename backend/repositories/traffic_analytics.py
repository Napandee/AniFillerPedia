"""Raw SQL data access for #221's daily Cloudflare traffic rollup.

Kept separate from repositories/admin.py (user-listing/role aggregate
queries) — different access pattern: one write per day, a small bounded
read for the dashboard, nothing paginated the way user listings are.
"""

import json

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_daily_rollup(
    session: AsyncSession,
    *,
    rollup_date,
    total_requests: int,
    top_paths: list[dict],
    status_breakdown: list[dict],
    top_countries: list[dict],
) -> None:
    """One row per UTC calendar day — ON CONFLICT (rollup_date) so a
    same-day rerun (worker restart, manual re-trigger) overwrites that
    day's row instead of accumulating duplicates, same idempotent-upsert
    shape as repositories/series_episode_schedule.py's upsert_schedule.
    """
    await session.execute(
        text(
            """
            INSERT INTO traffic_daily_rollups
                (rollup_date, total_requests, top_paths, status_breakdown, top_countries)
            VALUES
                (:rollup_date, :total_requests, CAST(:top_paths AS JSONB),
                 CAST(:status_breakdown AS JSONB), CAST(:top_countries AS JSONB))
            ON CONFLICT (rollup_date) DO UPDATE SET
                total_requests   = EXCLUDED.total_requests,
                top_paths        = EXCLUDED.top_paths,
                status_breakdown = EXCLUDED.status_breakdown,
                top_countries    = EXCLUDED.top_countries
            """
        ),
        {
            "rollup_date": rollup_date,
            "total_requests": total_requests,
            # asyncpg's JSONB binding needs an explicit JSON string, same
            # convention as repositories/series_proposals.py's episode_data
            # column — the reverse direction (reading a JSONB column back
            # out) needs no such handling, asyncpg decodes it to a native
            # Python list/dict automatically.
            "top_paths": json.dumps(top_paths),
            "status_breakdown": json.dumps(status_breakdown),
            "top_countries": json.dumps(top_countries),
        },
    )


async def list_daily_rollups(session: AsyncSession, limit: int = 30) -> list[Row]:
    """Most recent `limit` days, newest first — the dashboard's only real
    read pattern (see routers/admin.py's GET /admin/traffic).
    """
    result = await session.execute(
        text(
            """
            SELECT id, rollup_date, total_requests, top_paths, status_breakdown,
                   top_countries, created_at
            FROM traffic_daily_rollups
            ORDER BY rollup_date DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())
