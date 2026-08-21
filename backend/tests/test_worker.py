"""Real-Postgres tests for the outbox worker (#9's acceptance criteria) —
matches this project's own testing convention (AniDex's pr-validate.yml
pattern: exercise against a real throwaway Postgres, not mocks). Requires
DATABASE_URL to point at a live, schema-loaded Postgres.
"""

import asyncio

import pytest
from sqlalchemy import text

from core.db import async_session_factory
from worker import HANDLERS, process_batch


async def _insert_test_event(event_type: str, payload: dict) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO outbox_events (event_type, payload) "
                    "VALUES (:event_type, CAST(:payload AS JSONB)) RETURNING id"
                ),
                {"event_type": event_type, "payload": '{"note": "test"}'},
            )
            return result.scalar_one()


async def _cleanup(event_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM outbox_events WHERE id = :id"), {"id": event_id}
            )


@pytest.mark.asyncio
async def test_written_event_is_picked_up_and_marked_processed() -> None:
    calls: list[dict] = []

    async def _test_handler(payload: dict) -> None:
        calls.append(payload)

    HANDLERS["test.event"] = _test_handler
    event_id = await _insert_test_event("test.event", {"note": "test"})
    try:
        handled = await process_batch()
        assert handled >= 1
        assert len(calls) == 1

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT processed_at FROM outbox_events WHERE id = :id"),
                    {"id": event_id},
                )
            ).one()
            assert row.processed_at is not None
    finally:
        del HANDLERS["test.event"]
        await _cleanup(event_id)


@pytest.mark.asyncio
async def test_unhandled_event_type_stays_unprocessed() -> None:
    event_id = await _insert_test_event("no.handler.registered", {})
    try:
        await process_batch()
        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT processed_at FROM outbox_events WHERE id = :id"),
                    {"id": event_id},
                )
            ).one()
            assert row.processed_at is None
    finally:
        await _cleanup(event_id)


@pytest.mark.asyncio
async def test_concurrent_pollers_never_double_handle() -> None:
    """FOR UPDATE SKIP LOCKED must stop two concurrent batches from grabbing
    the same row — this is the entire reason that clause exists (CLAUDE.md
    Architecture: 'the same primitive real Postgres-backed queue libraries
    use'). Fire two process_batch() calls concurrently against one event and
    confirm the handler only ever ran once.
    """
    calls: list[dict] = []

    async def _test_handler(payload: dict) -> None:
        # Hold the row long enough that a genuinely concurrent second
        # poller would collide with it if SKIP LOCKED weren't working.
        await asyncio.sleep(0.05)
        calls.append(payload)

    HANDLERS["test.concurrent"] = _test_handler
    event_id = await _insert_test_event("test.concurrent", {})
    try:
        await asyncio.gather(process_batch(), process_batch())
        assert len(calls) == 1
    finally:
        del HANDLERS["test.concurrent"]
        await _cleanup(event_id)
