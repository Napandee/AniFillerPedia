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

from core.db import async_session_factory


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


async def record_independently(*, scope: str, identifier: str) -> None:
    """#257 security-review finding: contribution_submit and
    synonym_suggestion_submit both only ever called record() AFTER their
    guarded insert succeeded, inside the SAME transaction as everything
    else in the request — so a failed submission (404 series-not-found,
    409 duplicate-pending, 422 validation) never counted, and an attacker
    could probe either endpoint with deliberately-failing payloads for
    free. Unlike local_signup's own fix for this exact bug class
    (routers/auth.py), these two endpoints have no clean place to split
    a two-phase check+record block — their single caller-owned
    transaction is autobegun by an auth dependency's SELECT before the
    service function ever runs (see routers/contributions.py's own
    comment on this). So instead: record the attempt in a BRAND NEW
    session/connection/transaction, committed immediately, independent
    of the caller's session entirely. If the caller's transaction later
    rolls back (because the guarded work failed), this commit already
    happened on a different connection and is unaffected — "every
    attempt counts" without needing the caller's transaction boundaries
    touched at all.
    """
    async with async_session_factory() as session:
        async with session.begin():
            await record(session, scope=scope, identifier=identifier)


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


async def delete_for_user(session: AsyncSession, *, user_id: int, email: str | None) -> int:
    """#257 security-review finding: rate_limit_events.identifier can
    embed a deleted account's identity in two different shapes — the
    generic `user:<id>` form every authenticated-caller scope here uses
    (get_rate_limit_identifier, core/deps.py), and `local_login`'s own
    `login:<email>:<ip>` form (routers/auth.py builds that one directly,
    since login happens before there's a current_user to key on).
    DELETE /users/me never touched either, so a deleted account's rows —
    including an email embedded verbatim in the login scope — outlived
    the account forever. `identifier` has no FK to `users` (by design,
    per schema.sql: this table is transient bookkeeping, not an audit
    trail), so this is a plain text-match delete, not a cascade.
    """
    # Escaped so a literal '%' or '_' in the email can't widen the match
    # beyond this exact address — this is a delete, not a read, so an
    # unintended wildcard match would be a correctness bug, not just a
    # privacy one.
    escaped_email = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") if email else None
    result = await session.execute(
        text(
            """
            DELETE FROM rate_limit_events
            WHERE identifier = :user_identifier
               OR (
                   CAST(:login_pattern AS TEXT) IS NOT NULL
                   AND identifier LIKE CAST(:login_pattern AS TEXT) ESCAPE '\\'
               )
            RETURNING id
            """
        ),
        {
            "user_identifier": f"user:{user_id}",
            "login_pattern": f"login:{escaped_email}:%" if escaped_email else None,
        },
    )
    return len(result.fetchall())


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
