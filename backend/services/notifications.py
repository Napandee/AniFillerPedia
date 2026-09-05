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

#17 extracted the actual Telegram HTTP call into services/telegram.py
(shared with the new unhandled-error/deploy/uptime alerting) — this
module now only builds the message text and delegates the send, which
already never raises on its own, so the try/except below is purely
defense-in-depth against this module's own message-building logic.
"""

import logging

from services.telegram import send_telegram_message

logger = logging.getLogger(__name__)


def _build_message(payload: dict) -> str:
    if "contribution_id" in payload:
        return (
            f"New pending contribution #{payload['contribution_id']} — "
            f"series {payload.get('series_id')}, episode {payload.get('episode_number')}. "
            f"Review: https://anifillerpedia.wiki/moderation"
        )
    if "series_proposal_id" in payload:
        return (
            f"New series proposal #{payload['series_proposal_id']}: "
            f"{payload.get('title', '(untitled)')}. "
            f"Review: GET /api/v1/series-proposals?review_status=pending."
        )
    if "synonym_suggestion_id" in payload:
        return (
            f"New synonym suggestion #{payload['synonym_suggestion_id']} — "
            f"series {payload.get('series_id')}. "
            f"Review: GET /api/v1/synonym-suggestions?review_status=pending."
        )
    return f"New submission (unrecognized payload shape): {payload}"


async def notify_moderators_new_submission(payload: dict) -> None:
    try:
        text = _build_message(payload)
        await send_telegram_message(text)
    except Exception:
        logger.exception("Failed to build/send moderator notification for payload=%s", payload)
