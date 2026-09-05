"""Outbox consumer (#15): Cloudflare cache purge on approval, so the
Astro frontend's SSR pages (short edge-cache TTL, CLAUDE.md Architecture)
reflect an approval immediately rather than waiting on TTL expiry.
Registered into worker.py's HANDLERS for `contribution.approved` /
`series_proposal.approved` / `synonym_suggestion.approved`.

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

#189: this used to build a numeric `/series/{series_id}` URL, which #116's
slug-based routing left stale — `frontend/src/pages/series/[slug].astro`
is the only real route now, so a purge built against the numeric URL was
purging a path Cloudflare never actually cached, silently defeating the
whole "approved changes show up immediately" premise the outbox pattern
exists to deliver here. Fixed by having every write site that emits an
event this handler consumes embed the series' own `slug` directly in the
outbox payload (see services/contributions.py, services/series_proposals.py,
services/synonym_suggestions.py) — cheaper and simpler than this handler
doing its own DB lookup per event, and it's how outbox payloads already
carry every other piece of context a handler needs (CLAUDE.md Architecture).
"""

import logging

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


def build_series_purge_url(payload: dict, base_url: str) -> str | None:
    """Pure URL-building step, split out of purge_series_page_cache so a
    test can confirm the right path gets built for a series with a known
    slug without needing to mock an HTTP call (#189's own acceptance
    criteria). Returns None when the payload carries no slug to purge —
    the caller logs and no-ops in that case.
    """
    slug = payload.get("slug")
    if not slug:
        return None
    return f"{base_url}/series/{slug}"


async def purge_series_page_cache(payload: dict) -> None:
    settings = get_settings()
    series_id = payload.get("series_id")

    url_to_purge = build_series_purge_url(payload, settings.public_site_base_url)
    if url_to_purge is None:
        logger.warning(
            "cache-purge handler received a payload with no series slug "
            "(series_id=%s): %s — nothing to purge",
            series_id,
            payload,
        )
        return

    if not settings.cloudflare_api_token:
        logger.warning(
            "CLOUDFLARE_API_TOKEN not set — cache purge skipped for %s "
            "(structurally ready, not live-configured yet)",
            url_to_purge,
        )
        return

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
