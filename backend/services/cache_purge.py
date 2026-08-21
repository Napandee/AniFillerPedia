"""Outbox consumer (#15): Cloudflare cache purge on approval, so the
Astro frontend's SSR pages (short edge-cache TTL, CLAUDE.md Architecture)
reflect an approval immediately rather than waiting on TTL expiry.
Registered into worker.py's HANDLERS for `contribution.approved` /
`series_proposal.approved`.

Same never-raise design as services/notifications.py — see that module's
docstring for why (a raising handler rolls back the whole shared-batch
transaction, blocking unrelated events). A failed purge is logged, not
retried indefinitely, and does not block other outbox events.

The REST call shape and the real zone ID below were verified against
Cloudflare's live API on 2026-08-21 (a real purge_cache call against
zone 090a6d6b91e55f92740f23bad2c11de6 succeeded) — what's NOT verified is
this exact code path end-to-end inside the deployed app, since
CLOUDFLARE_API_TOKEN isn't provisioned yet (external-account checklist,
CLAUDE.local.md).
"""

import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


async def purge_series_page_cache(payload: dict) -> None:
    settings = get_settings()
    series_id = payload.get("series_id")
    if series_id is None:
        logger.warning("cache-purge handler received a payload with no series_id: %s — nothing to purge", payload)
        return

    if not settings.cloudflare_api_token:
        logger.warning(
            "CLOUDFLARE_API_TOKEN not set — cache purge skipped for series_id=%s "
            "(structurally ready, not live-configured yet)",
            series_id,
        )
        return

    # Purges both the series page and its episode-list variant — Astro's
    # actual route shape isn't decided yet (Phase 5 unbuilt), so this
    # purges the plausible URL now and should be revisited once real
    # frontend routes exist.
    url_to_purge = f"{settings.public_site_base_url}/series/{series_id}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{CLOUDFLARE_API_BASE}/zones/{settings.cloudflare_zone_id}/purge_cache",
                headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
                json={"files": [url_to_purge]},
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("success"):
                logger.error("Cloudflare purge_cache returned success=false for series_id=%s: %s", series_id, data)
    except Exception:
        logger.exception("Cloudflare cache purge failed for series_id=%s — not retried, see module docstring", series_id)
