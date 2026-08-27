"""Unhandled-error alerting (#17).

Fires a Telegram message when either the FastAPI app hits a genuine
unhandled exception (main.py's `exception_handler(Exception)` — a real
500, not an intentional HTTPException like a 404/403 the app already
raises deliberately) or the outbox worker's own poll loop raises
(worker.py's `run_forever`). Both cases would otherwise be a silent 500 /
silent crash-loop with nothing but a log line nobody's watching in real
time — same "structurally ready, not live-configured yet" pattern #15's
moderator-notification handler already uses (no real TELEGRAM_BOT_TOKEN
exists yet — see CLAUDE.local.md's external-account checklist). Reuses
services/telegram.py's shared sender rather than reimplementing the HTTP
call.

Never raises (send_telegram_message already never raises on its own —
this module's own try/except is defense-in-depth against message-building
here failing).

Fire-and-forget from an HTTP request path: main.py's exception handler
calls this via `asyncio.create_task(...)` rather than awaiting it
directly, specifically so a slow/failing Telegram call never turns one
application error into a hung response — see main.py's own comment at
the call site. The outbox worker's call site (worker.py) awaits this
directly instead, since it's a background poll loop with no request
waiting on it.
"""

import logging

from services.telegram import send_telegram_message

logger = logging.getLogger(__name__)


async def alert_unhandled_exception(context: str, exc: BaseException) -> None:
    """`context` is a short human-readable string identifying where this
    came from, e.g. "GET /api/v1/series/42" or "outbox worker poll loop".
    """
    try:
        text = f"AniFillerPedia: unhandled exception in {context}\n{type(exc).__name__}: {exc}"
        await send_telegram_message(text)
    except Exception:
        logger.exception("Failed to build/send unhandled-exception alert for context=%s", context)
