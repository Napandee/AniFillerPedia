"""One-time (but safely re-runnable) loader for issue #4: reads
series-candidates.json (already extracted from manami-project's archived
last snapshot) and upserts each entry into the live `series` table plus
its `series_synonyms` rows.

Idempotency note: `series.anilist_id`/`mal_id`/`anidb_id` are UNIQUE but
nullable, and Postgres never treats NULL = NULL for uniqueness — an
ON CONFLICT (anilist_id) clause would silently let two different runs
create duplicate all-NULL-crossref rows for the 6 candidates that lack an
anilist_id. So this does an explicit existence check per candidate
(by anilist_id when present, else by title) rather than relying on
ON CONFLICT for the series insert itself. series_synonyms has a real
NOT NULL composite UNIQUE(series_id, synonym), so ON CONFLICT DO NOTHING
is safe and used there.

Usage: DATABASE_URL=postgresql://... python3 load_series.py
(deliberately plain psycopg2 + a sync connection, not asyncpg/SQLAlchemy —
this is a standalone data-ops script, not part of the backend/ app's
import graph, and doesn't need async for a 180-row one-off load.)
"""

import json
import os
import sys
from pathlib import Path

import psycopg2

CANDIDATES_PATH = Path(__file__).parent / "series-candidates.json"


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    # This script uses plain psycopg2 (sync, no async driver needed) —
    # strip the +asyncpg suffix if the caller exported the app's own
    # async-flavored DATABASE_URL verbatim.
    return url.replace("postgresql+asyncpg://", "postgresql://")


def find_existing_series_id(cur, candidate: dict) -> int | None:
    if candidate.get("anilist_id"):
        cur.execute("SELECT id FROM series WHERE anilist_id = %s", (candidate["anilist_id"],))
    else:
        cur.execute("SELECT id FROM series WHERE title = %s", (candidate["title"],))
    row = cur.fetchone()
    return row[0] if row else None


def main() -> None:
    candidates = json.loads(CANDIDATES_PATH.read_text())
    print(f"Loaded {len(candidates)} candidates from {CANDIDATES_PATH.name}")

    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False
    inserted = 0
    already_present = 0
    synonyms_inserted = 0
    failures: list[tuple[str, str]] = []

    try:
        with conn.cursor() as cur:
            for candidate in candidates:
                title = candidate["title"]
                try:
                    existing_id = find_existing_series_id(cur, candidate)
                    if existing_id is not None:
                        series_id = existing_id
                        already_present += 1
                    else:
                        cur.execute(
                            """
                            INSERT INTO series (anilist_id, mal_id, anidb_id, title, provenance, added_by)
                            VALUES (%s, %s, %s, %s, 'manami_bootstrap', NULL)
                            RETURNING id
                            """,
                            (
                                candidate.get("anilist_id"),
                                candidate.get("mal_id"),
                                candidate.get("anidb_id"),
                                title,
                            ),
                        )
                        series_id = cur.fetchone()[0]
                        inserted += 1

                    for synonym in candidate.get("synonyms", []):
                        if not synonym:
                            continue
                        cur.execute(
                            """
                            INSERT INTO series_synonyms (series_id, synonym)
                            VALUES (%s, %s)
                            ON CONFLICT (series_id, synonym) DO NOTHING
                            """,
                            (series_id, synonym),
                        )
                        if cur.rowcount:
                            synonyms_inserted += 1
                except Exception as exc:  # noqa: BLE001 - report, don't silently skip
                    conn.rollback()
                    failures.append((title, str(exc)))
                    continue
                conn.commit()
    finally:
        conn.close()

    print(f"Inserted: {inserted}")
    print(f"Already present (skipped): {already_present}")
    print(f"Synonym rows inserted: {synonyms_inserted}")
    print(f"Failures: {len(failures)}")
    for title, err in failures:
        print(f"  - {title!r}: {err}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
