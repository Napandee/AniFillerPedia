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
