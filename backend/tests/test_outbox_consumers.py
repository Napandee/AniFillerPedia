"""Real-Postgres tests for #15's outbox consumers (Telegram notification,
Cloudflare cache purge), matching this project's real-infra testing
convention. No live TELEGRAM_BOT_TOKEN/CLOUDFLARE_API_TOKEN exist yet
(external-account checklist, CLAUDE.local.md) — these tests exercise the
real dispatch/resilience behavior, which doesn't require either token.

Also covers #189 (cache-purge slug-URL fix) and #195 (bounded retry +
dead-letter handling for a raising handler).
"""

import pytest
from sqlalchemy import text

from core.db import async_session_factory
from services.cache_purge import build_series_purge_url, purge_series_page_cache
from services.notifications import notify_moderators_new_submission
from worker import HANDLERS, MAX_RETRY_ATTEMPTS, process_batch


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


async def _event_state(event_id: int):
    async with async_session_factory() as session:
        return (
            await session.execute(
                text("SELECT processed_at, retry_count, failed_at FROM outbox_events WHERE id = :id"),
                {"id": event_id},
            )
        ).one()


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
async def test_purge_handler_with_no_slug_does_not_raise() -> None:
    # #189: series_id alone (no slug) is no longer enough to build a purge
    # URL — the handler must log and no-op rather than falling back to the
    # stale numeric-id URL #189 fixed away from.
    await purge_series_page_cache({"series_id": 1})


@pytest.mark.asyncio
async def test_purge_handler_with_missing_series_id_does_not_raise() -> None:
    await purge_series_page_cache({"contribution_id": 1})


@pytest.mark.asyncio
async def test_purge_handler_with_slug_and_no_token_does_not_raise() -> None:
    # #189: the realistic real-payload shape (slug present) with
    # CLOUDFLARE_API_TOKEN still unset (external-account checklist,
    # CLAUDE.local.md) — must still log-and-return, never raise.
    await purge_series_page_cache({"series_id": 8, "slug": "berserk"})


def test_build_series_purge_url_uses_slug_not_numeric_id() -> None:
    """#189's own acceptance criterion: a real test confirms the purge
    call targets the right (slug-based, #116) path for a series with a
    known slug — checked as a pure function so this doesn't need to mock
    an HTTP call to verify.
    """
    url = build_series_purge_url({"series_id": 8, "slug": "berserk"}, "https://anifillerpedia.wiki")
    assert url == "https://anifillerpedia.wiki/series/berserk"


def test_build_series_purge_url_returns_none_without_slug() -> None:
    assert build_series_purge_url({"series_id": 8}, "https://anifillerpedia.wiki") is None
    assert build_series_purge_url({}, "https://anifillerpedia.wiki") is None


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
    # #189: real payload shape now carries slug — this is what
    # services/contributions.py's _promote_to_episode_and_notify actually
    # writes.
    event_id = await _insert_test_event(
        "contribution.approved",
        '{"contribution_id": 999, "series_id": 1, "episode_number": 1, "slug": "__test_189__slug"}',
    )
    try:
        await process_batch()
        assert await _processed_at(event_id) is not None
    finally:
        await _cleanup(event_id)


@pytest.mark.asyncio
async def test_a_raising_handler_no_longer_blocks_other_events_in_the_same_batch() -> None:
    """#195: process_batch() now runs each event's handler + mark_processed
    in its own SAVEPOINT, so a raising handler can no longer roll back
    anything already committed earlier in the same batch — the exact
    head-of-line-blocking hazard #195 was filed to close. (Superseded
    version of this test's own prior assertions, which intentionally
    proved the OLD, now-fixed blocking behavior — see git history for
    that if the pre-#195 mechanism is ever relevant again.)
    """

    async def _broken_handler(payload: dict) -> None:
        raise RuntimeError("simulated failure — not a real #15 handler")

    async def _fine_handler(payload: dict) -> None:
        pass

    # Two events in the same poll; broken one sorts first (lower id) so it
    # fails before the fine one is processed.
    broken_id = await _insert_test_event("test.broken", "{}")
    fine_id = await _insert_test_event("test.fine", "{}")
    HANDLERS["test.broken"] = _broken_handler
    HANDLERS["test.fine"] = _fine_handler
    try:
        # No longer raises — the failure is caught and recorded per-event.
        await process_batch()

        broken_state = await _event_state(broken_id)
        assert broken_state.processed_at is None
        assert broken_state.retry_count == 1
        assert broken_state.failed_at is None  # below MAX_RETRY_ATTEMPTS, not dead-lettered yet

        # The fine event behind it was NOT blocked — this is the actual
        # bug #195 fixed.
        assert await _processed_at(fine_id) is not None
    finally:
        del HANDLERS["test.broken"]
        del HANDLERS["test.fine"]
        await _cleanup(broken_id)
        await _cleanup(fine_id)


@pytest.mark.asyncio
async def test_a_permanently_raising_handler_is_dead_lettered_after_max_retries() -> None:
    """#195's other acceptance criterion: after MAX_RETRY_ATTEMPTS failed
    attempts, a poisoned event is set aside (failed_at set) rather than
    retried forever, and stops being re-fetched by future poll cycles —
    the row itself stays in the table, queryable, not silently dropped.
    """
    call_count = 0

    async def _always_broken_handler(payload: dict) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated permanent failure")

    broken_id = await _insert_test_event("test.always_broken", "{}")
    HANDLERS["test.always_broken"] = _always_broken_handler
    try:
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            await process_batch()
            state = await _event_state(broken_id)
            assert state.retry_count == attempt
            if attempt < MAX_RETRY_ATTEMPTS:
                assert state.failed_at is None
        # Crossed the threshold — dead-lettered now.
        final_state = await _event_state(broken_id)
        assert final_state.failed_at is not None
        assert final_state.processed_at is None
        assert call_count == MAX_RETRY_ATTEMPTS

        # A further poll cycle must NOT re-fetch (and therefore not
        # re-invoke the handler for) a dead-lettered event — this is what
        # actually takes it out of the queue rather than just labeling it.
        await process_batch()
        assert call_count == MAX_RETRY_ATTEMPTS
    finally:
        del HANDLERS["test.always_broken"]
        await _cleanup(broken_id)
