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
    result = await session.execute(
        text(
            """
            SELECT id, event_type, payload, created_at
            FROM outbox_events
            WHERE processed_at IS NULL
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
