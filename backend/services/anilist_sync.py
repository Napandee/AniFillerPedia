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
from dataclasses import dataclass
from datetime import date

import httpx

from core.config import get_settings
from core.db import async_session_factory
from repositories.series_episode_schedule import (
    clear_drift_flag,
    list_finished_series_for_drift_check,
    list_series_needing_sync,
    mark_synced,
    set_drift_flag,
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

@dataclass
class AniListMediaSummary:
    """#165: the small, live-lookup-shaped subset of a Media object the
    series-proposal form's blur-triggered preview needs — deliberately
    not reusing _fetch_schedule's return shape (that's built for the
    batch daily-sync worker's own columns, e.g. airingSchedule pagination
    this single-request lookup has no use for)."""

    anilist_id: int
    title: str
    format: str | None
    episode_count: int | None
    cover_image_url: str | None


_LOOKUP_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english native }
    format
    episodes
    coverImage { extraLarge large }
  }
}
"""


async def fetch_anilist_media_summary(anilist_id: int) -> AniListMediaSummary | None:
    """#165: a live, single-request AniList lookup for the series-
    proposal form's blur-triggered preview — distinct from _fetch_schedule
    above, which is built for the daily sync worker (retry/backoff,
    airingSchedule pagination) and would be the wrong tool for a
    synchronous per-request call a real user is waiting on.

    Returns None for anything that isn't a clean, parseable 200 with a
    real Media object carrying at least one title — no such AniList id,
    a network error, a non-200 response, or a malformed body are all
    treated identically as "nothing to show," matching this module's
    existing "no data" convention (_fetch_schedule above does the same).
    A live user-facing path failing soft this way is a better failure
    mode than surfacing a raw 500 for what's ultimately a non-blocking,
    optional preview.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                ANILIST_ENDPOINT,
                json={"query": _LOOKUP_QUERY, "variables": {"id": anilist_id}},
                timeout=10.0,
            )
    except httpx.HTTPError:
        logger.warning("AniList live lookup request failed for anilist_id=%s", anilist_id, exc_info=True)
        return None

    if response.status_code != 200:
        return None

    try:
        body = response.json()
    except ValueError:
        return None

    media = (body or {}).get("data", {}).get("Media")
    if not media:
        return None

    title_fields = media.get("title") or {}
    title = title_fields.get("english") or title_fields.get("romaji") or title_fields.get("native")
    if not title:
        return None

    cover = media.get("coverImage") or {}
    cover_url = cover.get("extraLarge") or cover.get("large")

    return AniListMediaSummary(
        anilist_id=media.get("id") or anilist_id,
        title=title,
        format=media.get("format"),
        episode_count=media.get("episodes"),
        cover_image_url=cover_url,
    )


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


# --- #175: weekly drift re-check for series already marked FINISHED -------
#
# list_series_needing_sync() above permanently drops a series from the
# DAILY sync once anilist_status = 'FINISHED' — correct for cost (a
# genuinely finished show's schedule never changes again), but it means a
# real status change afterward (a show resuming from hiatus, more episodes
# added) is never re-detected. This is a second, independent, much cheaper
# query + loop specifically for that case: it re-checks every FINISHED
# series on a weekly cadence, but fetches only `status` + `episodes` — not
# coverImage/bannerImage/description/airingSchedule — since it's expected
# to almost always come back unchanged.

_DRIFT_CHECK_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    status
    episodes
  }
}
"""


async def _fetch_finished_series_status(
    client: httpx.AsyncClient, anilist_id: int
) -> tuple[str | None, int | None]:
    """Returns (status, episode_count) for one series' lightweight #175
    re-check — deliberately not reusing _fetch_schedule above, which
    fetches several extra fields this check has no use for and paginates
    airingSchedule, neither of which this query even requests. Mirrors
    _fetch_schedule's own retry/429-backoff pattern exactly (same
    _RATE_LIMIT_MAX_RETRIES / _RATE_LIMIT_RETRY_DELAY_SECONDS constants),
    minus the pagination loop, since this query has nothing to paginate.

    Never raises — a request failure, non-200, or malformed/empty body
    all come back as (None, None), the same "treat like no data"
    convention _fetch_schedule uses.
    """
    retries = 0
    while True:
        try:
            response = await client.post(
                ANILIST_ENDPOINT,
                json={"query": _DRIFT_CHECK_QUERY, "variables": {"id": anilist_id}},
                timeout=10.0,
            )
            if response.status_code == 429 and retries < _RATE_LIMIT_MAX_RETRIES:
                retries += 1
                logger.warning(
                    "AniList rate-limited during drift check (anilist_id=%s, attempt %s/%s) — backing off %ss",
                    anilist_id,
                    retries,
                    _RATE_LIMIT_MAX_RETRIES,
                    _RATE_LIMIT_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
                continue
            if response.status_code != 200:
                return None, None
            body = response.json()
            media = (body or {}).get("data", {}).get("Media")
            if not media:
                return None, None
            return media.get("status"), media.get("episodes")
        except (httpx.HTTPError, ValueError):
            logger.exception("AniList drift-check fetch failed for anilist_id=%s", anilist_id)
            return None, None


def _detect_drift(
    *,
    live_status: str | None,
    live_episode_count: int | None,
    recorded_episode_count: int | None,
    max_researched_episode: int,
) -> str | None:
    """Pure decision function (#175's drift definition) — kept separate
    from the fetch/DB-write plumbing so it's trivially unit-testable.
    Returns the drift reason ('status_drift' | 'episode_count_drift') or
    None if no drift is detected. A None live_status (the fetch itself
    failed) is treated as "nothing learned this cycle" by the caller, not
    routed through this function at all — see check_finished_series_drift.

    status_drift takes priority: a series that's no longer FINISHED at
    all is the more fundamental change, and checking it first means an
    episode-count comparison never even needs to run for that case.
    """
    if live_status is not None and live_status != "FINISHED":
        return "status_drift"
    if live_episode_count is not None:
        known_baseline = max(recorded_episode_count or 0, max_researched_episode)
        if live_episode_count > known_baseline:
            return "episode_count_drift"
    return None


async def check_finished_series_drift() -> int:
    """One weekly drift-check cycle. Returns how many series had their
    drift-flag STATE actually change this cycle (newly flagged, newly
    cleared, or reason changed) — not how many were checked, since almost
    every cycle is expected to find nothing (matching this module's own
    "log only when something real happened" convention, e.g.
    sync_episode_schedules' "if synced: logger.info(...)" above).

    Opens its own DB transaction per series, same reasoning as
    sync_episode_schedules: a slow/hung AniList request never holds a
    long-lived transaction open, and one series' failure can't roll back
    another's already-committed flag update.
    """
    async with async_session_factory() as session:
        async with session.begin():
            candidates = await list_finished_series_for_drift_check(session)

    if not candidates:
        return 0

    changed = 0
    async with httpx.AsyncClient() as client:
        for series in candidates:
            live_status, live_episode_count = await _fetch_finished_series_status(
                client, series.anilist_id
            )
            if live_status is None:
                # Fetch failed outright — never touch the existing flag on
                # a failed check, same "no data = no change" convention
                # used throughout this module.
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)
                continue

            reason = _detect_drift(
                live_status=live_status,
                live_episode_count=live_episode_count,
                recorded_episode_count=series.anilist_episode_count,
                max_researched_episode=series.max_researched_episode,
            )

            async with async_session_factory() as session:
                async with session.begin():
                    if reason is not None:
                        await set_drift_flag(session, series_id=series.id, reason=reason)
                    else:
                        await clear_drift_flag(session, series_id=series.id)
            if reason != series.previous_drift_reason:
                changed += 1
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
    return changed


async def run_finished_series_drift_check_forever() -> None:
    settings = get_settings()
    logger.info(
        "finished-series drift check starting: interval=%ss",
        settings.finished_series_drift_check_interval_seconds,
    )
    while True:
        try:
            changed = await check_finished_series_drift()
            if changed:
                logger.info("finished-series drift state changed for %s series", changed)
        except Exception:
            logger.exception("error during finished-series drift check cycle — continuing")
        await asyncio.sleep(settings.finished_series_drift_check_interval_seconds)
