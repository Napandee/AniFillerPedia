"""Generic per-scope/per-identifier rate-limit bookkeeping (#139/#141) —
backs simple rolling-window throttles on the anonymous-accessible write
endpoints that have no natural per-account row to count against the way
#84's bulk_submission_events/count_recent_bulk_submissions does (an
anonymous caller has no user id to key on). `identifier` is caller-
supplied — a "user:<id>" string when authenticated, an "ip:<address>"
string otherwise — and `scope` names the endpoint/limit being enforced, so
one endpoint's counter never eats into another's budget for the same
caller.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def count_recent(
    session: AsyncSession, *, scope: str, identifier: str, window_seconds: int
) -> int:
    result = await session.execute(
        text(
            """
            SELECT count(*) FROM rate_limit_events
            WHERE scope = :scope AND identifier = :identifier
              AND created_at > now() - make_interval(secs => :window_seconds)
            """
        ),
        {"scope": scope, "identifier": identifier, "window_seconds": window_seconds},
    )
    return result.scalar_one()


async def record(session: AsyncSession, *, scope: str, identifier: str) -> None:
    await session.execute(
        text("INSERT INTO rate_limit_events (scope, identifier) VALUES (:scope, :identifier)"),
        {"scope": scope, "identifier": identifier},
    )


async def list_recent_grouped(
    session: AsyncSession, *, window_hours: int, limit: int
) -> list:
    """Per (scope, identifier) counts within the window, most-active
    first — the abuse-signal dashboard panel's data source (#250)."""
    result = await session.execute(
        text(
            """
            SELECT scope, identifier, count(*) AS event_count,
                   min(created_at) AS first_seen, max(created_at) AS last_seen
            FROM rate_limit_events
            WHERE created_at > now() - make_interval(hours => :window_hours)
            GROUP BY scope, identifier
            ORDER BY event_count DESC
            LIMIT :limit
            """
        ),
        {"window_hours": window_hours, "limit": limit},
    )
    return list(result.fetchall())


async def count_recent_totals(session: AsyncSession, *, window_hours: int):
    """Headline totals for the same window, independent of list_recent_
    grouped's LIMIT — so a summary sentence stays accurate even when the
    detail table is truncated (#250)."""
    result = await session.execute(
        text(
            """
            SELECT count(*) AS total_events, count(DISTINCT identifier) AS distinct_identifiers
            FROM rate_limit_events
            WHERE created_at > now() - make_interval(hours => :window_hours)
            """
        ),
        {"window_hours": window_hours},
    )
    return result.one()
