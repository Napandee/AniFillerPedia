"""Shared low-level Telegram Bot API sender.

Extracted from services/notifications.py (#15) as part of #17 so every
Telegram-sending path in this project — #15's moderator notification on a
new pending submission, and #17's unhandled-error / deploy-failure /
uptime alerts — goes through the exact same HTTP-call shape instead of
each reimplementing it. This is deliberately the ONLY place that calls
Telegram's `sendMessage` endpoint.

Never raises: every caller in this project uses this from a context that
must not let a slow/failing Telegram API call become a request hang, a
crash-looping worker, or a failed batch (see services/notifications.py's
and services/alerting.py's own docstrings for the specific reasons each
of their callers can't tolerate a raise here).
"""

import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


async def send_telegram_message(text: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN not set — Telegram message skipped (structurally ready, "
            "not live-configured yet): %s",
            text,
        )
        return

    url = f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
            response.raise_for_status()
    except Exception:
        logger.exception("Telegram sendMessage failed — not retried: %s", text)
