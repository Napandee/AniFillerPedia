"""Outbox consumer (#15): Telegram notification to moderators on a new
pending submission. Registered into worker.py's HANDLERS for
`contribution.submitted` / `series_proposal.submitted`.

Design note — why this never raises: worker.py's process_batch() wraps an
entire batch (up to worker_batch_size rows) in ONE transaction. If a
handler raises, that whole transaction rolls back, undoing mark_processed
for every row already handled in the same batch — not just the failing
one. That would mean a persistently-failing Telegram call (e.g. missing
token) blocks unrelated events (like #15's own cache-purge handler)
sharing a batch, forever. #15's own acceptance criteria explicitly
requires handler failures not to block other events, so this handler
always catches its own errors, logs them, and returns normally — a failed
notification is visible in logs, not silently lost, but it does not hold
up the batch or retry indefinitely (retrying a structurally-missing token
forever would never succeed anyway).
"""

import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


def _build_message(payload: dict) -> str:
    if "contribution_id" in payload:
        return (
            f"New pending contribution #{payload['contribution_id']} — "
            f"series {payload.get('series_id')}, episode {payload.get('episode_number')}. "
            f"Review: GET /api/v1/contributions?review_status=pending "
            f"(no moderation UI yet — Phase 5 frontend not built)."
        )
    if "series_proposal_id" in payload:
        return (
            f"New series proposal #{payload['series_proposal_id']}: "
            f"{payload.get('title', '(untitled)')}. "
            f"Review: GET /api/v1/series-proposals?review_status=pending."
        )
    return f"New submission (unrecognized payload shape): {payload}"


async def notify_moderators_new_submission(payload: dict) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN not set — moderator notification skipped for payload=%s "
            "(structurally ready, not live-configured yet)",
            payload,
        )
        return

    text = _build_message(payload)
    url = f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
            response.raise_for_status()
    except Exception:
        logger.exception("Telegram notification failed for payload=%s — not retried, see module docstring", payload)
