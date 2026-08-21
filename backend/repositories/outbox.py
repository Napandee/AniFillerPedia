"""Raw SQL data access for outbox_events — the only place that touches this
table directly. `FOR UPDATE SKIP LOCKED` is what makes concurrent pollers
(multiple worker replicas, if this ever scales that way) safe: a row locked
by one poller is invisible to another rather than blocking it.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


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
