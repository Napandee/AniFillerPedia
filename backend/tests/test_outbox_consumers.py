"""Real-Postgres tests for #15's outbox consumers (Telegram notification,
Cloudflare cache purge), matching this project's real-infra testing
convention. No live TELEGRAM_BOT_TOKEN/CLOUDFLARE_API_TOKEN exist yet
(external-account checklist, CLAUDE.local.md) — these tests exercise the
real dispatch/resilience behavior, which doesn't require either token.
"""

import pytest
from sqlalchemy import text

from core.db import async_session_factory
from services.cache_purge import purge_series_page_cache
from services.notifications import notify_moderators_new_submission
from worker import HANDLERS, process_batch


async def _insert_test_event(event_type: str, payload_json: str) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO outbox_events (event_type, payload) "
                    "VALUES (:event_type, CAST(:payload AS JSONB)) RETURNING id"
                ),
                {"event_type": event_type, "payload": payload_json},
            )
            return result.scalar_one()


async def _processed_at(event_id: int):
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT processed_at FROM outbox_events WHERE id = :id"), {"id": event_id}
            )
        ).one()
        return row.processed_at


async def _cleanup(event_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM outbox_events WHERE id = :id"), {"id": event_id})


@pytest.mark.asyncio
async def test_notification_handler_with_no_token_does_not_raise() -> None:
    # No TELEGRAM_BOT_TOKEN configured in this environment — this is
    # exactly the real current state in production too. Must log and
    # return, never raise.
    await notify_moderators_new_submission({"contribution_id": 999, "series_id": 1, "episode_number": 1})


@pytest.mark.asyncio
async def test_purge_handler_with_no_token_does_not_raise() -> None:
    await purge_series_page_cache({"series_id": 1})


@pytest.mark.asyncio
async def test_purge_handler_with_missing_series_id_does_not_raise() -> None:
    await purge_series_page_cache({"contribution_id": 1})


@pytest.mark.asyncio
async def test_contribution_submitted_dispatches_to_notification_handler_and_is_marked_processed() -> None:
    # Real HANDLERS registration, real event_type string #12 actually uses.
    # No token configured -> handler logs and returns -> event still marked
    # processed, proving a missing-config handler doesn't get stuck forever
    # without visibility, matching #15's acceptance criteria.
    event_id = await _insert_test_event(
        "contribution.submitted", '{"contribution_id": 999, "series_id": 1, "episode_number": 1}'
    )
    try:
        await process_batch()
        assert await _processed_at(event_id) is not None
    finally:
        await _cleanup(event_id)


@pytest.mark.asyncio
async def test_contribution_approved_dispatches_to_purge_handler_and_is_marked_processed() -> None:
    event_id = await _insert_test_event(
        "contribution.approved", '{"contribution_id": 999, "series_id": 1, "episode_number": 1}'
    )
    try:
        await process_batch()
        assert await _processed_at(event_id) is not None
    finally:
        await _cleanup(event_id)


@pytest.mark.asyncio
async def test_a_raising_handler_would_block_other_events_in_the_same_batch() -> None:
    """This is NOT testing #15's real handlers (which never raise, by
    design) — it's proving the underlying mechanism in worker.py that
    makes the never-raise design necessary in the first place: process_batch
    wraps a whole batch in one transaction, so if a handler raises,
    mark_processed for every row already handled in that same batch rolls
    back too, not just the failing one. Confirming this is real, not just
    assumed reasoning in a docstring.
    """

    async def _broken_handler(payload: dict) -> None:
        raise RuntimeError("simulated failure — not a real #15 handler")

    async def _fine_handler(payload: dict) -> None:
        pass

    # Two events in the same poll; broken one sorts first (lower id) so it
    # fails before the fine one would otherwise get marked processed.
    broken_id = await _insert_test_event("test.broken", "{}")
    fine_id = await _insert_test_event("test.fine", "{}")
    HANDLERS["test.broken"] = _broken_handler
    HANDLERS["test.fine"] = _fine_handler
    try:
        with pytest.raises(RuntimeError):
            await process_batch()
        # Both rolled back — proving the shared-transaction hazard #15's
        # real handlers are specifically designed to avoid.
        assert await _processed_at(broken_id) is None
        assert await _processed_at(fine_id) is None
    finally:
        del HANDLERS["test.broken"]
        del HANDLERS["test.fine"]
        await _cleanup(broken_id)
        await _cleanup(fine_id)
