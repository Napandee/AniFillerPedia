"""One-off (but safely re-runnable) backfill for issue #133: within-franchise
watch-order navigation.

Deliberately placed in scripts/, not data/bootstrap/ — this doesn't read
anything from data/bootstrap (titles are resolved directly against the
`series` table), and a separate session was actively working under
data/bootstrap/ at the time this was written; keeping this script out of
that directory avoids any merge-conflict risk with that work.

For each franchise group below (in decided watch order), this script:
  1. Resolves each title to its series.id via an exact-title SELECT.
  2. Sets series.sequence_order = 1, 2, 3, ... in that order.
  3. Ensures series_relations has the full symmetric closure for the group
     (every ordered pair, both directions) via ON CONFLICT DO NOTHING —
     idempotent even when some of the closure already exists (e.g. Fairy
     Tail's original 3-member closure, per issue #133's own comment).

Any title that doesn't resolve to exactly one series row is reported and
that franchise is skipped entirely (not partially applied) — see #133's
own scope note against silently skipping without flagging.

Usage: DATABASE_URL=postgresql://... python3 backfill_series_sequence_order.py
(plain psycopg2 + sync connection, same convention as data/bootstrap/
load_series.py — a standalone data-ops script, not part of backend/'s async
app import graph.)
"""

import os
import sys

import psycopg2

# Issue #133: the 9 franchises + their decided watch order. Room is
# deliberately left in Bleach's group for a future "Kashin-tan"/"The
# Calamity" 4th part (not loaded yet) — sequence_order values are assigned
# only to what's listed here, so a future 5th row can just be appended.
FRANCHISES: list[list[str]] = [
    [
        "Fairy Tail",
        "Fairy Tail (2014)",
        "Fairy Tail (2018)",
        "Fairy Tail: 100-nen Quest",
    ],
    [
        "Naruto",
        "Naruto: Shippuuden",
        "Boruto: Naruto Next Generations",
    ],
    [
        "Bishoujo Senshi Sailor Moon",
        "Bishoujo Senshi Sailor Moon R",
        "Bishoujo Senshi Sailor Moon S",
        "Bishoujo Senshi Sailor Moon SuperS",
        "Bishoujo Senshi Sailor Moon: Sailor Stars",
        # Bishoujo Senshi Sailor Moon Crystal deliberately excluded — a
        # separate reboot/remake, not part of this watch-order chain.
    ],
    [
        "GANTZ",
        "GANTZ 2",
    ],
    [
        "Rosario to Vampire",
        "Rosario to Vampire Capu2",
    ],
    [
        "Shadows House",
        "Shadows House 2nd Season",
    ],
    [
        "Shugo Chara!",
        "Shugo Chara!! Doki",
        "Shugo Chara! Party!",
    ],
    [
        "Bleach",
        "Bleach: Sennen Kessen-hen",
        "Bleach: Sennen Kessen-hen - Ketsubetsu-tan",
        "Bleach: Sennen Kessen-hen - Soukoku-tan",
        # Room left for a future 4th part ("Kashin-tan"/"The Calamity"),
        # not loaded yet — it would get sequence_order = 5.
    ],
    [
        "Shokugeki no Souma",
        "Shokugeki no Souma: Ni no Sara",
        "Shokugeki no Souma: San no Sara",
        "Shokugeki no Souma: Shin no Sara",
        "Shokugeki no Souma: Gou no Sara",
    ],
]


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return url.replace("postgresql+asyncpg://", "postgresql://")


def resolve_title(cur, title: str) -> int | None:
    cur.execute("SELECT id FROM series WHERE title = %s", (title,))
    rows = cur.fetchall()
    if len(rows) != 1:
        return None
    return rows[0][0]


def main() -> None:
    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False

    sequence_order_set = 0
    relation_rows_inserted = 0
    unresolved: list[str] = []
    franchises_applied = 0
    franchises_skipped: list[tuple[int, str]] = []

    try:
        with conn.cursor() as cur:
            for group in FRANCHISES:
                ids: list[int] = []
                group_unresolved = []
                for title in group:
                    series_id = resolve_title(cur, title)
                    if series_id is None:
                        group_unresolved.append(title)
                    else:
                        ids.append(series_id)

                if group_unresolved:
                    unresolved.extend(group_unresolved)
                    franchises_skipped.append((len(group), group[0]))
                    print(
                        f"SKIPPING franchise starting with {group[0]!r}: "
                        f"could not resolve {group_unresolved!r} to exactly one series row each"
                    )
                    continue

                for position, series_id in enumerate(ids, start=1):
                    cur.execute(
                        "UPDATE series SET sequence_order = %s WHERE id = %s",
                        (position, series_id),
                    )
                    sequence_order_set += cur.rowcount

                # Full symmetric closure: every ordered pair, both directions.
                for a in ids:
                    for b in ids:
                        if a == b:
                            continue
                        cur.execute(
                            """
                            INSERT INTO series_relations (series_id, related_series_id)
                            VALUES (%s, %s)
                            ON CONFLICT (series_id, related_series_id) DO NOTHING
                            """,
                            (a, b),
                        )
                        relation_rows_inserted += cur.rowcount

                franchises_applied += 1
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print()
    print(f"Franchises applied: {franchises_applied}/{len(FRANCHISES)}")
    print(f"Franchises skipped (unresolved title): {len(franchises_skipped)}")
    for size, first_title in franchises_skipped:
        print(f"  - group starting {first_title!r} ({size} members)")
    print(f"series.sequence_order rows set: {sequence_order_set}")
    print(f"series_relations rows inserted (new, ON CONFLICT DO NOTHING): {relation_rows_inserted}")
    if unresolved:
        print(f"Unresolved titles ({len(unresolved)}): {unresolved!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
