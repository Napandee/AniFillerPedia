"""Outbox worker entrypoint — polls outbox_events and dispatches each row to
a handler registered for its event_type. This is the mechanism only (#9);
the actual handlers (Telegram notification, Cloudflare cache purge) are
#15's scope and get registered into HANDLERS from there, not here.

An event_type with no registered handler is deliberately left unprocessed
rather than marked done — so nothing is ever silently dropped once a real
handler exists for it later. Run as its own container (docker-compose.yml
`worker` service), same image as the app, different entrypoint.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from core.config import get_settings
from core.db import async_session_factory
from repositories.outbox import fetch_unprocessed_batch, mark_processed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox_worker")

# event_type -> async handler(payload: dict) -> None. Populated by #15;
# empty here on purpose — see module docstring.
HANDLERS: dict[str, Callable[[dict], Awaitable[None]]] = {}


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
        except Exception:
            logger.exception("error during outbox poll cycle — continuing")
        await asyncio.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_forever())
