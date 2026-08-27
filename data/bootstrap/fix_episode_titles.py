"""#124-ish: apply verified episode-title corrections found by sweeping the
whole catalog with the fixed wiki_scrape_v3.py extractor (see
CLAUDE.local.md "Update 2026-08-27").

Reads a JSON file of corrections in the shape:
    [{"slug": "bleach", "episode_number": 348, "title": "..."}, ...]

For each entry, looks up the series by `slug`, and UPDATEs that episode's
`title` — nothing else (status/citation_ids/source_count untouched). Uses
psycopg2 %s placeholders throughout, never string interpolation or
shell-embedded SQL, specifically to avoid the exact quote-escaping failure
mode already hit once today (an embedded `"` lost through a layered
shell/SSH/docker-exec `-c` argument, silently truncating a title 2
characters short — see CLAUDE.local.md).

After applying, reads back `length(title)` for every touched row and
compares it against the expected length client-side, so a silent
truncation would be caught immediately rather than assumed away from a
"looks right" psql readout.

Usage:
  DATABASE_URL=... python3 fix_episode_titles.py <corrections.json> [--dry-run]
"""

import json
import os
import sys

import psycopg2


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return url.replace("postgresql+asyncpg://", "postgresql://")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    corrections = json.load(open(path, encoding="utf-8"))
    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False
    cur = conn.cursor()

    applied = []
    missing = []
    for c in corrections:
        slug = c["slug"]
        ep_num = c["episode_number"]
        new_title = c["title"]

        cur.execute("SELECT id FROM series WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row is None:
            missing.append((slug, ep_num, "series not found"))
            continue
        series_id = row[0]

        cur.execute(
            "SELECT id, title FROM episodes WHERE series_id = %s AND episode_number = %s",
            (series_id, ep_num),
        )
        ep_row = cur.fetchone()
        if ep_row is None:
            missing.append((slug, ep_num, "episode not found"))
            continue
        episode_id, old_title = ep_row

        if dry_run:
            print(f"[dry-run] {slug} ep{ep_num}: {old_title!r} -> {new_title!r}")
            continue

        cur.execute(
            "UPDATE episodes SET title = %s WHERE id = %s",
            (new_title, episode_id),
        )
        applied.append((slug, ep_num, episode_id, new_title))

    if dry_run:
        conn.rollback()
        print(f"\n[dry-run] {len(corrections)} corrections would be applied, "
              f"{len(missing)} not found.")
        return

    conn.commit()

    # Read back and verify length — never trust a "looks right" readout.
    mismatches = []
    for slug, ep_num, episode_id, expected_title in applied:
        cur.execute("SELECT title, length(title) FROM episodes WHERE id = %s", (episode_id,))
        got_title, got_len = cur.fetchone()
        expected_len = len(expected_title)
        if got_title != expected_title or got_len != expected_len:
            mismatches.append((slug, ep_num, expected_title, expected_len, got_title, got_len))

    cur.close()
    conn.close()

    print(f"Applied {len(applied)} corrections.")
    if missing:
        print(f"{len(missing)} entries not found (series/episode missing):")
        for m in missing:
            print("  ", m)
    if mismatches:
        print(f"!!! {len(mismatches)} VERIFICATION MISMATCHES (possible truncation):")
        for m in mismatches:
            print("  ", m)
        sys.exit(1)
    else:
        print("All applied titles verified byte-for-byte (length + content match) on readback.")


if __name__ == "__main__":
    main()
