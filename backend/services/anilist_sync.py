"""#49: repeatable, cadence-aware AniList episode-count/air-date sync.

Populates series_episode_schedule for every series with a known
anilist_id — separate from `episodes`, which only ever gets a row once
real canon/filler research is approved (see schema.sql). A series already
confirmed FINISHED from a prior sync isn't re-fetched on later runs; only
RELEASING (or never-synced) series are — so an ongoing show's schedule
keeps updating cycle over cycle while a finished one (e.g. Naruto:
Shippuden) stops needing outbound calls at all once confirmed done.

Runs as a second, independently-paced loop inside the existing worker
container (see worker.py) — not a new container or new infrastructure.

One series per HTTP round-trip, not one big batched query like the
frontend's cover-art fetch (frontend/src/lib/anilist.ts) — a batched
`Page(media(id_in: $ids))` query can't paginate each series' own
airingSchedule independently, and a long-running show's complete air-date
history can span multiple pages. This runs on a daily cadence, not a
request path, so the extra round-trips cost nothing that matters.
"""

import asyncio
import logging

import httpx

from core.config import get_settings
from core.db import async_session_factory
from repositories.series_episode_schedule import (
    list_series_needing_sync,
    mark_synced,
    upsert_schedule,
)

logger = logging.getLogger("anilist_sync")

ANILIST_ENDPOINT = "https://graphql.anilist.co"

_QUERY = """
query ($id: Int, $page: Int) {
  Media(id: $id, type: ANIME) {
    status
    episodes
    airingSchedule(page: $page, perPage: 50) {
      pageInfo { hasNextPage }
      nodes { episode airingAt }
    }
  }
}
"""

# Polite spacing against AniList's shared rate limit (90 req/min) — this
# worker isn't time-sensitive (daily cadence), so a small delay between
# requests costs nothing and avoids ever tripping it during a large first
# backfill across every series in the catalog.
_REQUEST_DELAY_SECONDS = 0.7


async def _fetch_schedule(
    client: httpx.AsyncClient, anilist_id: int
) -> tuple[str | None, int | None, list[dict]]:
    """Returns (anilist_status, episode_count, [{"episode": int,
    "airingAt": int}, ...]) for one series, paginating airingSchedule
    fully. Never raises — a request failure or malformed response just
    comes back as (None, None, []), the same "treat like no data"
    convention the frontend's own AniList integration uses (anilist.ts).

    episode_count (Media.episodes) is captured separately from the
    schedule nodes because AniList's airingSchedule field only retains a
    rolling window — confirmed live that a long-finished 500-episode show
    returns only its last 3 episodes' worth of nodes, not a full
    historical archive, while episode_count itself stays reliable.
    """
    status: str | None = None
    episode_count: int | None = None
    nodes: list[dict] = []
    page = 1
    while True:
        try:
            response = await client.post(
                ANILIST_ENDPOINT,
                json={"query": _QUERY, "variables": {"id": anilist_id, "page": page}},
                timeout=10.0,
            )
            if response.status_code != 200:
                break
            body = response.json()
            media = (body or {}).get("data", {}).get("Media")
            if not media:
                break
            status = media.get("status")
            episode_count = media.get("episodes")
            schedule = media.get("airingSchedule") or {}
            page_nodes = schedule.get("nodes") or []
            nodes.extend(page_nodes)
            if not (schedule.get("pageInfo") or {}).get("hasNextPage"):
                break
            page += 1
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
        except (httpx.HTTPError, ValueError):
            logger.exception("AniList schedule fetch failed for anilist_id=%s", anilist_id)
            break
    return status, episode_count, nodes


async def sync_episode_schedules() -> int:
    """One sync cycle. Returns how many series were actually synced.
    Opens its own DB transaction per series (rather than one transaction
    for the whole cycle) so a slow or hung AniList request never holds a
    long-lived transaction open, and one series' failure can't roll back
    another's already-committed sync.
    """
    async with async_session_factory() as session:
        async with session.begin():
            candidates = await list_series_needing_sync(session)

    if not candidates:
        return 0

    synced = 0
    async with httpx.AsyncClient() as client:
        for series in candidates:
            status, episode_count, nodes = await _fetch_schedule(client, series.anilist_id)
            if status is not None:
                episodes = [
                    (node["episode"], node["airingAt"])
                    for node in nodes
                    if isinstance(node.get("episode"), int) and node.get("airingAt") is not None
                ]
                async with async_session_factory() as session:
                    async with session.begin():
                        if episodes:
                            await upsert_schedule(session, series_id=series.id, episodes=episodes)
                        await mark_synced(
                            session,
                            series_id=series.id,
                            anilist_status=status,
                            anilist_episode_count=episode_count,
                        )
                synced += 1
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
    return synced


async def run_episode_schedule_sync_forever() -> None:
    settings = get_settings()
    logger.info(
        "episode schedule sync starting: interval=%ss",
        settings.episode_schedule_sync_interval_seconds,
    )
    while True:
        try:
            synced = await sync_episode_schedules()
            if synced:
                logger.info("synced episode schedule for %s series", synced)
        except Exception:
            logger.exception("error during episode schedule sync cycle — continuing")
        await asyncio.sleep(settings.episode_schedule_sync_interval_seconds)
