"""#73: partial episode-title backfill from AniList's own `streamingEpisodes`
field (sourced from Crunchyroll's catalog listing), NOT from hand-compiled
research — titles aren't a filler/canon judgment call, they're factual
metadata, the same category as #49/#51's air dates.

Confirmed live 2026-08-23 against Naruto (AniList id 20): `streamingEpisodes`
returns real per-episode titles in the form "Episode N - Actual Title", but
it's a PARTIAL/rolling field like `airingSchedule` — only 26 of Naruto's 220
episodes came back, apparently whatever Crunchyroll's own catalog page
listed at scrape time, with no pagination argument on the field to ask for
more. This script only ever fills what AniList actually has; every episode
outside that window stays null (rendered as "Episode #N" by the frontend,
same graceful-degradation convention as an unsynced air date) rather than
being guessed at or hand-typed, which would undercut this project's whole
cited/cross-referenced sourcing model for something that isn't even a
canon/filler claim.

Never overwrites an already-set title (whether set by a prior run of this
script or by load_episodes.py's own optional "title" field) — idempotent
and safe to re-run as AniList's own listing changes over time.

Usage:
  DATABASE_URL=... python3 backfill_episode_titles_from_anilist.py
      (all series with an anilist_id and at least one loaded episode)
  DATABASE_URL=... python3 backfill_episode_titles_from_anilist.py "Naruto" "Bleach"
      (restrict to specific series titles)

(plain psycopg2 + httpx sync client, matching load_episodes.py/load_series.py's
own precedent — a standalone data-ops script, not part of the backend/ app's
async import graph.)
"""

import os
import re
import sys
import time

_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    streamingEpisodes { title }
  }
}
"""

# Same politeness convention as backend/services/anilist_sync.py — this
# script isn't time-sensitive, a slower pace costs nothing.
_REQUEST_DELAY_SECONDS = 1.5
_RATE_LIMIT_RETRY_DELAY_SECONDS = 10.0
_RATE_LIMIT_MAX_RETRIES = 3

_TITLE_PATTERN = re.compile(r"^Episode\s+\d+\s*-\s*(.+)$")


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return url.replace("postgresql+asyncpg://", "postgresql://")


def fetch_streaming_titles(client, anilist_id: int) -> dict[int, str]:
    """Returns {episode_number: title} for whatever AniList's
    streamingEpisodes actually has (see module docstring — partial, not a
    full archive). Never raises — a failed/malformed call just yields no
    titles for this series, same "treat like no data" convention #49 uses
    throughout.
    """
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            response = client.post(
                "https://graphql.anilist.co",
                json={"query": _QUERY, "variables": {"id": anilist_id}},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
            print(f"  request failed: {exc}", file=sys.stderr)
            return {}

        if response.status_code == 429 and attempt < _RATE_LIMIT_MAX_RETRIES:
            time.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
            continue
        if response.status_code != 200:
            print(f"  AniList returned {response.status_code}", file=sys.stderr)
            return {}

        nodes = (
            response.json().get("data", {}).get("Media", {}).get("streamingEpisodes")
            or []
        )
        titles: dict[int, str] = {}
        for index, node in enumerate(nodes, start=1):
            match = _TITLE_PATTERN.match(node.get("title") or "")
            if match:
                # streamingEpisodes has no explicit episode-number field —
                # position in the (ordered) list is the number, confirmed
                # against Naruto's real response (episode 1 first, etc.).
                titles[index] = match.group(1).strip()
        return titles
    return {}


def main() -> None:
    import httpx
    import psycopg2

    restrict_to = sys.argv[1:] or None

    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if restrict_to:
                cur.execute(
                    """
                    SELECT DISTINCT s.id, s.title, s.anilist_id
                    FROM series s
                    JOIN episodes e ON e.series_id = s.id
                    WHERE s.anilist_id IS NOT NULL AND s.title = ANY(%s)
                    ORDER BY s.title
                    """,
                    (restrict_to,),
                )
            else:
                cur.execute(
                    """
                    SELECT DISTINCT s.id, s.title, s.anilist_id
                    FROM series s
                    JOIN episodes e ON e.series_id = s.id
                    WHERE s.anilist_id IS NOT NULL
                    ORDER BY s.title
                    """
                )
            target_series = cur.fetchall()

        if not target_series:
            print("No matching series with an anilist_id and loaded episodes found.")
            return

        with httpx.Client() as client:
            for series_id, series_title, anilist_id in target_series:
                print(f"{series_title} (anilist_id={anilist_id}):")
                titles = fetch_streaming_titles(client, anilist_id)
                if not titles:
                    print("  no streamingEpisodes titles available")
                    time.sleep(_REQUEST_DELAY_SECONDS)
                    continue

                with conn.cursor() as cur:
                    updated = 0
                    for episode_number, title in titles.items():
                        cur.execute(
                            """
                            UPDATE episodes SET title = %s
                            WHERE series_id = %s AND episode_number = %s AND title IS NULL
                            """,
                            (title, series_id, episode_number),
                        )
                        updated += cur.rowcount
                    conn.commit()
                print(f"  {len(titles)} titles available from AniList, {updated} episodes updated (rest already had a title or don't exist here)")
                time.sleep(_REQUEST_DELAY_SECONDS)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
