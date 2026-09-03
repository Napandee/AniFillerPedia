"""Outbox worker entrypoint — polls outbox_events and dispatches each row to
a handler registered for its event_type. The mechanism itself is #9; the
handlers below (Telegram notification, Cloudflare cache purge) are #15.

An event_type with no registered handler is deliberately left unprocessed
rather than marked done — so nothing is ever silently dropped once a real
handler exists for it later. Run as its own container (docker-compose.yml
`worker` service), same image as the app, different entrypoint.

Every handler registered here MUST NOT raise — process_batch() wraps a
whole batch in one transaction, so a raising handler rolls back
mark_processed for every row already handled in that same batch, not just
its own. See services/notifications.py's module docstring for the full
reasoning. Handlers catch their own errors and log them instead.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from core.config import get_settings
from core.db import async_session_factory
from repositories.outbox import fetch_unprocessed_batch, mark_processed
from services.alerting import alert_unhandled_exception
from services.anilist_sync import (
    run_episode_schedule_sync_forever,
    run_finished_series_drift_check_forever,
)
from services.cache_purge import purge_series_page_cache
from services.notifications import notify_moderators_new_submission

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox_worker")

# event_type -> async handler(payload: dict) -> None.
#
# contribution.approved / series_proposal.approved event_type strings
# match the dotted convention #12 already established for .submitted
# (verified directly in services/contributions.py and
# services/series_proposals.py) — #13 (moderator approve/reject, running
# in parallel) is expected to use these same two names when it writes
# outbox events on approval. If #13 lands with different names, update
# the keys below to match rather than changing #13's naming after the
# fact — .submitted's convention is the one already shipped and tested.
HANDLERS: dict[str, Callable[[dict], Awaitable[None]]] = {
    "contribution.submitted": notify_moderators_new_submission,
    "series_proposal.submitted": notify_moderators_new_submission,
    "contribution.approved": purge_series_page_cache,
    "series_proposal.approved": purge_series_page_cache,
    # #148: same two consumers, reused as-is — notify_moderators_new_
    # submission's _build_message() gained a synonym_suggestion_id branch,
    # and purge_series_page_cache already keys purely off payload
    # {"series_id": ...}, which every one of this event's payloads carries
    # (a synonym approval changes what a series' own detail page shows).
    "synonym_suggestion.submitted": notify_moderators_new_submission,
    "synonym_suggestion.approved": purge_series_page_cache,
}


async def process_batch() -> int:
    """One poll cycle. Returns how many events were actually handled."""
    settings = get_settings()
    handled = 0
    async with async_session_factory() as session:
        async with session.begin():
            rows = await fetch_unprocessed_batch(session, settings.worker_batch_size)
            for row in rows:
                handler = HANDLERS.get(row.event_type)
                if handler is None:
                    logger.warning(
                        "no handler registered for event_type=%s (id=%s) — left unprocessed",
                        row.event_type,
                        row.id,
                    )
                    continue
                await handler(row.payload)
                await mark_processed(session, row.id)
                handled += 1
    return handled


async def run_forever() -> None:
    settings = get_settings()
    logger.info(
        "outbox worker starting: poll_interval=%ss batch_size=%s",
        settings.worker_poll_interval_seconds,
        settings.worker_batch_size,
    )
    while True:
        try:
            handled = await process_batch()
            if handled:
                logger.info("processed %s event(s)", handled)
        except Exception as exc:
            logger.exception("error during outbox poll cycle — continuing")
            # #17: alert on the worker's own unhandled failures rather than
            # silently crash-looping — awaited directly (not
            # fire-and-forget) since this is a background poll loop, not a
            # request path nothing is blocked on waiting for a response.
            await alert_unhandled_exception("outbox worker poll loop", exc)
        await asyncio.sleep(settings.worker_poll_interval_seconds)


async def run_all_forever() -> None:
    """#49: runs the outbox poller and the AniList episode-schedule sync
    as independent loops in the same container/process, each on its own
    cadence — no new container or infrastructure needed for this.

    #175: renamed from run_both_forever() to accommodate a third loop —
    the weekly finished-series drift re-check — alongside the original
    two. Still one asyncio.gather, still one container/process.
    """
    await asyncio.gather(
        run_forever(),
        run_episode_schedule_sync_forever(),
        run_finished_series_drift_check_forever(),
    )


if __name__ == "__main__":
    asyncio.run(run_all_forever())
