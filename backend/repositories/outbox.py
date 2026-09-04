"""Raw SQL data access for outbox_events — the only place that touches this
table directly. `FOR UPDATE SKIP LOCKED` is what makes concurrent pollers
(multiple worker replicas, if this ever scales that way) safe: a row locked
by one poller is invisible to another rather than blocking it.
"""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def write(session: AsyncSession, *, event_type: str, payload: dict[str, Any]) -> None:
    """Producer-side half of the outbox pattern (#9's worker is the
    consumer side, which only had fetch/mark_processed until now). Callers
    must invoke this inside the same transaction as the state change it
    reports (CLAUDE.md Architecture) — this function doesn't commit or
    open its own transaction, it just executes the INSERT against whatever
    session/transaction the caller is already in.
    """
    await session.execute(
        text("INSERT INTO outbox_events (event_type, payload) VALUES (:event_type, CAST(:payload AS JSONB))"),
        {"event_type": event_type, "payload": json.dumps(payload)},
    )


async def fetch_unprocessed_batch(session: AsyncSession, limit: int) -> list[Row]:
    """#195: excludes dead-lettered rows (failed_at IS NOT NULL) as well as
    already-processed ones — a dead-lettered event has permanently given up
    (see mark_dead_lettered below) and must stop being re-fetched every
    poll cycle, which is what makes dead-lettering actually take a poisoned
    event OUT of the queue rather than just labeling it while it keeps
    getting retried forever anyway.
    """
    result = await session.execute(
        text(
            """
            SELECT id, event_type, payload, created_at, retry_count
            FROM outbox_events
            WHERE processed_at IS NULL AND failed_at IS NULL
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


async def mark_processed(session: AsyncSession, event_id: int) -> None:
    await session.execute(
        text("UPDATE outbox_events SET processed_at = now() WHERE id = :id"),
        {"id": event_id},
    )


async def increment_retry_count(session: AsyncSession, event_id: int) -> int:
    """#195: called when a handler raises for this event — records the
    failed attempt and returns the new total so the caller (worker.py) can
    decide whether this attempt crossed the dead-letter threshold.
    """
    result = await session.execute(
        text(
            "UPDATE outbox_events SET retry_count = retry_count + 1 "
            "WHERE id = :id RETURNING retry_count"
        ),
        {"id": event_id},
    )
    return result.scalar_one()


async def mark_dead_lettered(session: AsyncSession, event_id: int) -> None:
    """#195: sets an event aside after it has exhausted its retry budget —
    fetch_unprocessed_batch above excludes it from now on, so it stops
    head-of-line-blocking everything behind it, while the row itself (and
    its failed_at/retry_count) stays in the table, queryable, rather than
    being silently dropped.
    """
    await session.execute(
        text("UPDATE outbox_events SET failed_at = now() WHERE id = :id"),
        {"id": event_id},
    )
