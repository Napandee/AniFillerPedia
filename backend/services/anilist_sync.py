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

One series per HTTP round-trip, not one big batched `Page(media(id_in:
$ids))` query — that shape can't paginate each series' own airingSchedule
independently, and a long-running show's complete air-date history can
span multiple pages. This runs on a daily cadence, not a request path, so
the extra round-trips cost nothing that matters.

Also syncs cover/banner art (2026-08-22 follow-up to #46): originally
fetched live from AniList on every single frontend page load, which meant
a real AniList outage took down cover art site-wide, all at once, since
it was a synchronous per-request third-party dependency. Cover/banner
URLs are effectively static per series, so they're synced here on the
same cadence as everything else instead, and the frontend just reads them
from our own API like any other field.
"""

import asyncio
import html as html_module
import logging
import re
from datetime import date

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
    description(asHtml: false)
    startDate { year month day }
    endDate { year month day }
    coverImage { extraLarge }
    bannerImage
    airingSchedule(page: $page, perPage: 50) {
      pageInfo { hasNextPage }
      nodes { episode airingAt }
    }
  }
}
"""

_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_anilist_description(raw: str | None) -> str | None:
    """#126: AniList's `asHtml: false` does NOT reliably strip HTML —
    confirmed live (One Piece's description still came back with
    `<br><br>` and `<b>` tags even with asHtml: false). This does the
    mechanical cleanup only: `<br>`/`<br/>` become paragraph breaks
    (`\\n\\n`), every other tag is stripped, and HTML entities are
    unescaped. Deliberately does NOT attempt to heuristically detect and
    strip trailing "(Source: ...)" attribution lines or "includes the
    following special episodes" footnotes some entries append — that's a
    fragile per-show judgment call that risks wrongly truncating real
    content for a different show (see issue #126).

    Returns None for a None/empty/whitespace-only input, never an empty
    string, matching this project's "store nothing rather than a blank
    placeholder" convention elsewhere.
    """
    if not raw:
        return None
    text = _BR_TAG_RE.sub("\n\n", raw)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    text = text.strip()
    return text or None


def _parse_anilist_date(value: dict | None) -> date | None:
    """Only constructs a real DATE when year, month, AND day are all
    present — AniList's {year, month, day} objects can have any subset
    null (e.g. a show announced with only a year known), and this
    project's existing convention (see #51/#55) is to store nothing
    rather than a partial/fabricated value.
    """
    if not value:
        return None
    year, month, day = value.get("year"), value.get("month"), value.get("day")
    if year is None or month is None or day is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None

# Polite spacing against AniList's shared rate limit (nominally 90 req/min,
# but confirmed live 2026-08-22 that a large first backfill across the
# whole 180-series catalog still tripped 429s at 0.7s spacing — AniList's
# real in-practice ceiling runs lower than its documented limit under
# load). This worker isn't time-sensitive (daily cadence), so a slower
# pace and a real retry-with-backoff on 429 (below) cost nothing.
_REQUEST_DELAY_SECONDS = 1.5
_RATE_LIMIT_RETRY_DELAY_SECONDS = 10.0
_RATE_LIMIT_MAX_RETRIES = 3


async def _fetch_schedule(
    client: httpx.AsyncClient, anilist_id: int
) -> tuple[
    str | None,
    int | None,
    str | None,
    str | None,
    str | None,
    date | None,
    date | None,
    list[dict],
]:
    """Returns (anilist_status, episode_count, cover_url, banner_url,
    description, start_date, end_date, [{"episode": int, "airingAt": int},
    ...]) for one series, paginating airingSchedule fully. Never raises —
    a request failure or malformed response just comes back as (None,
    None, None, None, None, None, None, []), the same "treat like no
    data" convention this project uses throughout for a failed AniList
    call.

    episode_count (Media.episodes) is captured separately from the
    schedule nodes because AniList's airingSchedule field only retains a
    rolling window — confirmed live that a long-finished 500-episode show
    returns only its last 3 episodes' worth of nodes, not a full
    historical archive, while episode_count itself stays reliable.
    """
    status: str | None = None
    episode_count: int | None = None
    cover_url: str | None = None
    banner_url: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    nodes: list[dict] = []
    page = 1
    retries = 0
    while True:
        try:
            response = await client.post(
                ANILIST_ENDPOINT,
                json={"query": _QUERY, "variables": {"id": anilist_id, "page": page}},
                timeout=10.0,
            )
            if response.status_code == 429 and retries < _RATE_LIMIT_MAX_RETRIES:
                retries += 1
                logger.warning(
                    "AniList rate-limited (anilist_id=%s, attempt %s/%s) — backing off %ss",
                    anilist_id,
                    retries,
                    _RATE_LIMIT_MAX_RETRIES,
                    _RATE_LIMIT_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
                continue
            if response.status_code != 200:
                break
            retries = 0
            body = response.json()
            media = (body or {}).get("data", {}).get("Media")
            if not media:
                break
            status = media.get("status")
            episode_count = media.get("episodes")
            cover_url = (media.get("coverImage") or {}).get("extraLarge")
            banner_url = media.get("bannerImage")
            description = clean_anilist_description(media.get("description"))
            start_date = _parse_anilist_date(media.get("startDate"))
            end_date = _parse_anilist_date(media.get("endDate"))
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
    return status, episode_count, cover_url, banner_url, description, start_date, end_date, nodes


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
            (
                status,
                episode_count,
                cover_url,
                banner_url,
                description,
                start_date,
                end_date,
                nodes,
            ) = await _fetch_schedule(client, series.anilist_id)
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
                            anilist_cover_url=cover_url,
                            anilist_banner_url=banner_url,
                            anilist_description=description,
                            anilist_start_date=start_date,
                            anilist_end_date=end_date,
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
