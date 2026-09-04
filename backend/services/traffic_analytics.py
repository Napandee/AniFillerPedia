"""#221: daily Cloudflare zone-analytics rollup — implementation of #219's
spike decision (see that issue's closing comment for the full reasoning).

Cloudflare's own zone analytics already passively covers both the Astro
frontend and `/api/v1/*` (verified live in #219's research) with zero
client-side code and zero cookies, since Cloudflare proxies both alike.
This module queries the GraphQL Analytics API (`httpRequestsAdaptiveGroups`
dataset) once a day for the prior 24h window and persists a small rollup
into Postgres — Cloudflare's own retention window for this dataset is
short, so this is what gives the project permanent history.

Runs as a fourth, independently-paced loop inside the existing worker
container (see worker.py), alongside the outbox poller, #49's episode-
schedule sync, and #175's drift check — same "own interval setting, own
run_..._forever() function" pattern all three already use.

**Requires a real `CLOUDFLARE_ANALYTICS_API_TOKEN`, which does not exist
yet** (Zone > Analytics > Read, scoped to this zone — a *different*,
narrower-scoped token than services/cache_purge.py's own
`CLOUDFLARE_API_TOKEN`, which is Zone > Cache Purge). Follows the same
"structurally ready, no-ops gracefully while unconfigured" convention as
services/turnstile.py's verify() and services/telegram.py's
send_telegram_message(): while the token is unset, run_daily_traffic_
rollup() logs once (not every cycle — see _logged_missing_token below)
and returns without erroring, so the worker never crash-loops over a
credential that simply hasn't been provisioned yet.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from core.config import get_settings
from core.db import async_session_factory
from repositories.traffic_analytics import upsert_daily_rollup

logger = logging.getLogger("traffic_analytics")

CLOUDFLARE_GRAPHQL_ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"

# This exact query shape (httpRequestsAdaptiveGroups, grouped by path/
# method/status/country) was already verified live against this zone in
# #219's own research spike — reused as-is here, not reinvented.
_QUERY = """
query TrafficRollup($zoneTag: String!, $since: Time!, $until: Time!, $limit: Int!) {
  viewer {
    zones(filter: { zoneTag: $zoneTag }) {
      httpRequestsAdaptiveGroups(
        filter: { datetime_geq: $since, datetime_lt: $until }
        limit: $limit
        orderBy: [count_DESC]
      ) {
        count
        dimensions {
          clientRequestPath
          clientRequestHTTPMethodName
          edgeResponseStatus
          clientCountryName
        }
      }
    }
  }
}
"""

# Cloudflare's own cap on this dataset's limit argument is well above this
# (docs put it in the thousands) — this is a daily rollup over a 24h
# window, not an exhaustive per-request export, so a few thousand distinct
# (path, method, status, country) combinations is already generous headroom
# for a site this project's own traffic volume.
_QUERY_LIMIT = 5000

_TOP_N_PATHS = 15
_TOP_N_COUNTRIES = 10

# #221's own acceptance criteria: log the missing-token skip once, not
# every cycle. With a daily interval this would barely matter (one line a
# day is not "spam" by any real measure), but this still follows the
# letter of the instruction, and it costs nothing.
_logged_missing_token = False


def _classify_path_kind(path: str) -> str:
    """frontend vs. api split, per #221's own scope: "split on whether the
    path starts with /api/v1/"."""
    return "api" if path.startswith("/api/v1/") else "frontend"


def aggregate_rollup(
    groups: list[dict],
    *,
    top_n_paths: int = _TOP_N_PATHS,
    top_n_countries: int = _TOP_N_COUNTRIES,
) -> dict:
    """Pure aggregation step, split out of run_daily_traffic_rollup so it's
    testable with a plain list of Cloudflare-shaped group dicts — no
    HTTP/DB involved. `groups` is the raw `httpRequestsAdaptiveGroups`
    array: [{"count": int, "dimensions": {"clientRequestPath": str,
    "clientRequestHTTPMethodName": str, "edgeResponseStatus": int,
    "clientCountryName": str}}, ...].

    Cloudflare groups by the full (path, method, status, country) tuple,
    so the same path/status/country each show up split across several
    input rows — this collapses each dimension down to its own total
    (summed across every other dimension) before ranking, rather than
    reporting only the single highest-count tuple per path/status/country.
    """
    total_requests = 0
    path_counts: dict[str, int] = {}
    status_counts: dict[int, int] = {}
    country_counts: dict[str, int] = {}

    for group in groups:
        count = group.get("count") or 0
        dimensions = group.get("dimensions") or {}
        total_requests += count

        path = dimensions.get("clientRequestPath")
        if path:
            path_counts[path] = path_counts.get(path, 0) + count

        status = dimensions.get("edgeResponseStatus")
        if status is not None:
            status_counts[status] = status_counts.get(status, 0) + count

        country = dimensions.get("clientCountryName")
        if country:
            country_counts[country] = country_counts.get(country, 0) + count

    top_paths = [
        {"path": path, "path_kind": _classify_path_kind(path), "count": count}
        for path, count in sorted(path_counts.items(), key=lambda kv: kv[1], reverse=True)[
            :top_n_paths
        ]
    ]
    # Every distinct status code, not just a top-N slice — the set of
    # status codes a real deployment produces is naturally small, so
    # there's no benefit to truncating it the way paths/countries need.
    status_breakdown = [
        {"status": status, "count": count}
        for status, count in sorted(status_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    top_countries = [
        {"country": country, "count": count}
        for country, count in sorted(country_counts.items(), key=lambda kv: kv[1], reverse=True)[
            :top_n_countries
        ]
    ]

    return {
        "total_requests": total_requests,
        "top_paths": top_paths,
        "status_breakdown": status_breakdown,
        "top_countries": top_countries,
    }


async def _fetch_traffic_groups(
    *, token: str, zone_id: str, since: datetime, until: datetime
) -> list[dict] | None:
    """Returns the raw `httpRequestsAdaptiveGroups` array, or None on any
    failure (non-2xx, malformed body, GraphQL-level `errors`) — never
    raises, matching the "a failed fetch means no data, not a crash"
    convention services/anilist_sync.py's own HTTP calls already use.
    """
    variables = {
        "zoneTag": zone_id,
        "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": _QUERY_LIMIT,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                CLOUDFLARE_GRAPHQL_ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
                json={"query": _QUERY, "variables": variables},
            )
            response.raise_for_status()
            body = response.json()
    except Exception:
        logger.exception(
            "Cloudflare GraphQL Analytics API request failed — traffic rollup skipped this cycle"
        )
        return None

    if body.get("errors"):
        logger.error("Cloudflare GraphQL Analytics API returned errors: %s", body["errors"])
        return None

    try:
        zones = body["data"]["viewer"]["zones"]
    except (KeyError, TypeError):
        logger.error(
            "Cloudflare GraphQL Analytics API returned an unexpected response shape: %s", body
        )
        return None

    if not zones:
        # A real, if unlikely, outcome — the token's zone scope doesn't
        # match cloudflare_zone_id, or the zone has no data for the window.
        # Not an error: an empty rollup (total_requests=0) is a legitimate
        # persisted result, not a skip.
        return []
    return zones[0].get("httpRequestsAdaptiveGroups", [])


async def run_daily_traffic_rollup() -> bool:
    """One rollup cycle: fetch the prior 24h window, aggregate, persist.
    Returns True if a rollup was actually persisted, False if this cycle
    no-op'd (no token configured, or the Cloudflare fetch failed — already
    logged by _fetch_traffic_groups in the latter case).
    """
    global _logged_missing_token
    settings = get_settings()

    if not settings.cloudflare_analytics_api_token:
        if not _logged_missing_token:
            logger.warning(
                "CLOUDFLARE_ANALYTICS_API_TOKEN not set — traffic rollup skipped "
                "(structurally ready, not live-configured yet; this message logs "
                "once, not every cycle)"
            )
            _logged_missing_token = True
        return False

    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=24)

    groups = await _fetch_traffic_groups(
        token=settings.cloudflare_analytics_api_token,
        zone_id=settings.cloudflare_zone_id,
        since=since,
        until=until,
    )
    if groups is None:
        return False

    rollup = aggregate_rollup(groups)

    async with async_session_factory() as session:
        async with session.begin():
            await upsert_daily_rollup(
                session,
                rollup_date=until.date(),
                total_requests=rollup["total_requests"],
                top_paths=rollup["top_paths"],
                status_breakdown=rollup["status_breakdown"],
                top_countries=rollup["top_countries"],
            )
    return True


async def run_traffic_rollup_forever() -> None:
    settings = get_settings()
    logger.info(
        "traffic rollup starting: interval=%ss",
        settings.traffic_rollup_interval_seconds,
    )
    while True:
        try:
            persisted = await run_daily_traffic_rollup()
            if persisted:
                logger.info("persisted daily traffic rollup")
        except Exception:
            logger.exception("error during traffic rollup cycle — continuing")
        await asyncio.sleep(settings.traffic_rollup_interval_seconds)
