"""#49: general-purpose (not series-specific) loader for hand-compiled
episode-data JSON files in the shape documented by data/bootstrap/README.md
— `series_title`, `citation_sources` (list of {id, url, description}), and
`episodes` (list of {episode_number, status, citation_ids, status_note?}).
Looks up the target series by title and inserts pre-approved contributions
+ episodes rows for anything not already loaded.

Citation merging: schema.sql's contributions/episodes tables take exactly
ONE citation_id each, not a list, but the source JSON's episodes each cite
1+ source ids. This collapses each unique combination of citation_ids used
by any episode into a single citations row, shared by every episode citing
that same combination (typically far fewer combinations than episodes — a
whole arc usually cites the same sources). A single-source combination
keeps that source's real url/description untouched; a multi-source
combination has no one representative url (citations.url can only hold
one link), so url is left NULL and every source's description (with its
own url folded in, when it has one) is combined into one description
instead.

Idempotent: an episode_number already present in `episodes` for the target
series is skipped, not overwritten — re-running this script after adding
more researched episodes to the same JSON file only inserts what's new.
Every episode is loaded as an already-approved contribution
(resolution_method='moderator', submitted_by=NULL) — this is a bootstrap
import of research already vetted before being written into the JSON
file, the same provenance model load_series.py already established for
the series catalog's own bootstrap import.

Usage: DATABASE_URL=postgresql://... python3 load_episodes.py <path-to-json>
(plain psycopg2 + sync connection, matching load_series.py's own
precedent — a standalone data-ops script, not part of the backend/ app's
async import graph, and doesn't need async for what's at most a few
thousand rows per show.)
"""

import json
import os
import sys
from pathlib import Path


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    # This script uses plain psycopg2 (sync) — strip the +asyncpg suffix if
    # the caller exported the app's own async-flavored DATABASE_URL verbatim.
    return url.replace("postgresql+asyncpg://", "postgresql://")


def find_series_id(cur, title: str) -> int | None:
    cur.execute("SELECT id FROM series WHERE title = %s", (title,))
    row = cur.fetchone()
    return row[0] if row else None


def merge_citation(source_ids: tuple[str, ...], sources_by_id: dict) -> tuple[str | None, str]:
    sources = [sources_by_id[sid] for sid in source_ids]
    if len(sources) == 1:
        return sources[0].get("url"), sources[0]["description"]
    parts = []
    for source in sources:
        if source.get("url"):
            parts.append(f"{source['description']} ({source['url']})")
        else:
            parts.append(source["description"])
    return None, " / ".join(parts)


def main() -> None:
    import psycopg2

    if len(sys.argv) != 2:
        print("Usage: DATABASE_URL=... python3 load_episodes.py <path-to-json>", file=sys.stderr)
        sys.exit(1)

    json_path = Path(sys.argv[1])
    data = json.loads(json_path.read_text())
    series_title = data["series_title"]
    sources_by_id = {source["id"]: source for source in data["citation_sources"]}
    episodes = data["episodes"]
    print(f"Loaded {len(episodes)} episodes for {series_title!r} from {json_path.name}")

    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False
    inserted = 0
    already_present = 0
    failures: list[tuple[int, str]] = []
    # combo (sorted tuple of source ids) -> citation_id. Populated as
    # combinations are encountered; each citation insert is committed
    # immediately (see below) so it survives even if a later episode using
    # the same combination fails.
    citation_id_by_combo: dict[tuple[str, ...], int] = {}

    try:
        with conn.cursor() as cur:
            series_id = find_series_id(cur, series_title)
            if series_id is None:
                print(f"No series found with title {series_title!r} — aborting", file=sys.stderr)
                sys.exit(1)

            for episode in episodes:
                episode_number = episode["episode_number"]
                try:
                    cur.execute(
                        "SELECT 1 FROM episodes WHERE series_id = %s AND episode_number = %s",
                        (series_id, episode_number),
                    )
                    if cur.fetchone():
                        already_present += 1
                        continue

                    combo = tuple(sorted(episode["citation_ids"]))
                    citation_id = citation_id_by_combo.get(combo)
                    if citation_id is None:
                        url, description = merge_citation(combo, sources_by_id)
                        cur.execute(
                            "INSERT INTO citations (url, description) VALUES (%s, %s) RETURNING id",
                            (url, description),
                        )
                        citation_id = cur.fetchone()[0]
                        # Committed on its own, independent of the
                        # contribution/episode insert below — so a later
                        # failure on THIS episode rolls back only its own
                        # contribution/episode rows, never a citation
                        # another already-loaded episode may also be using.
                        conn.commit()
                        citation_id_by_combo[combo] = citation_id

                    cur.execute(
                        """
                        INSERT INTO contributions
                            (series_id, episode_number, proposed_status, proposed_note,
                             citation_id, submitted_by, review_status, resolution_method,
                             license_accepted)
                        VALUES
                            (%s, %s, %s, %s, %s, NULL, 'approved', 'moderator', true)
                        RETURNING id
                        """,
                        (
                            series_id,
                            episode_number,
                            episode["status"],
                            episode.get("status_note"),
                            citation_id,
                        ),
                    )
                    contribution_id = cur.fetchone()[0]

                    cur.execute(
                        """
                        INSERT INTO episodes
                            (series_id, episode_number, status, status_note,
                             citation_id, approved_contribution_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            series_id,
                            episode_number,
                            episode["status"],
                            episode.get("status_note"),
                            citation_id,
                            contribution_id,
                        ),
                    )
                    inserted += 1
                except Exception as exc:  # noqa: BLE001 - report, don't silently skip
                    conn.rollback()
                    failures.append((episode_number, str(exc)))
                    continue
                conn.commit()
    finally:
        conn.close()

    print(f"Inserted: {inserted}")
    print(f"Already present (skipped): {already_present}")
    print(f"Citation rows created: {len(citation_id_by_combo)}")
    print(f"Failures: {len(failures)}")
    for episode_number, err in failures:
        print(f"  - episode {episode_number}: {err}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
