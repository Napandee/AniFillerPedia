"""Issue #116 — one-time backfill for the `series.slug` column added by
011_add_series_slug.sql. Must be run once, immediately after that
migration, against the same database (local test-pg first, then
production).

Generates a slug from each row's `title` via services/slugs.py's shared
slugify_title() — the same rule repositories/series.py's create() applies
to brand-new series going forward, so this script and that code path can
never drift apart. Processes rows ordered by id (oldest first) so that,
should a collision ever occur among *today's* real catalog, the
lower-id/earlier series keeps the clean base slug and later ones get
disambiguated — an arbitrary but stable tie-break, consistent with this
project's general preference for deterministic, explainable behavior over
insertion-order accidents.

Collision handling: tracks every slug assigned so far in this run (a
plain in-memory set) — if a title's base slug is already taken (by an
earlier row in this same run, or already present in the database from a
previous partial run), the row's own numeric id is appended
(services/slugs.py's disambiguate_slug) to disambiguate. Idempotent: a
row that already has a non-NULL slug is left untouched, so re-running
this script after a partial failure only fills in what's still missing.

(Plain psycopg2 + sync connection, matching load_series.py/load_episodes.py's
own precedent — a standalone data-ops script, not part of the backend/
app's async import graph.)

Usage:
  DATABASE_URL=... python3 011_backfill_series_slugs.py
  DATABASE_URL=... python3 011_backfill_series_slugs.py --dry-run
"""

import os
import sys

# This script lives in backend/migrations/, one level below backend/ where
# services/ lives — add backend/ to the import path so `from services.slugs
# import ...` resolves the same way it does for the real app.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import psycopg2  # noqa: E402

from services.slugs import disambiguate_slug, slugify_title  # noqa: E402


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    # This script uses plain psycopg2 (sync) — strip the +asyncpg suffix if
    # the caller exported the app's own async-flavored DATABASE_URL verbatim.
    return url.replace("postgresql+asyncpg://", "postgresql://")


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]

    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Existing non-NULL slugs (from a prior partial run, or any
            # series already created post-#116 via repositories.series.create())
            # must be respected as already-taken, not just this run's own
            # assignments.
            cur.execute("SELECT slug FROM series WHERE slug IS NOT NULL")
            used_slugs: set[str] = {row[0] for row in cur.fetchall()}

            cur.execute(
                "SELECT id, title FROM series WHERE slug IS NULL ORDER BY id"
            )
            rows = cur.fetchall()

            print(f"{len(rows)} series without a slug; {len(used_slugs)} slugs already assigned.")

            assignments: list[tuple[int, str]] = []
            for series_id, title in rows:
                base_slug = slugify_title(title)
                slug = base_slug
                if slug in used_slugs:
                    slug = disambiguate_slug(base_slug, series_id)
                    # Still theoretically colliding (e.g. two titles that
                    # already differ only by an id-shaped suffix) — fall
                    # back to guaranteed-unique id-only in that vanishingly
                    # unlikely case rather than loop forever.
                    if slug in used_slugs:
                        slug = f"series-{series_id}"
                used_slugs.add(slug)
                assignments.append((series_id, slug))
                print(f"  #{series_id} {title!r} -> {slug}")

            if dry_run:
                print("--dry-run: no changes written.")
                conn.rollback()
                return

            for series_id, slug in assignments:
                cur.execute(
                    "UPDATE series SET slug = %s WHERE id = %s", (slug, series_id)
                )

            conn.commit()
            print(f"Backfilled {len(assignments)} slugs.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
