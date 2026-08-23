"""#49: general-purpose (not series-specific) loader for hand-compiled
episode-data JSON files in the shape documented by data/bootstrap/README.md
— `series_title`, `citation_sources` (list of {id, url, description,
methodology_note?}), and `episodes` (list of {episode_number, status,
citation_ids, status_note?}). Looks up the target series by title and
inserts pre-approved contributions + episodes rows for anything not
already loaded.

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

Idempotent by default: an episode_number already present in `episodes` for
the target series is skipped if its status already matches the JSON's, not
overwritten — re-running this script after adding more researched episodes
to the same JSON file only inserts what's new.

An episode that already exists with a DIFFERENT status than the JSON
proposes is a real disagreement, not something to silently skip or
silently overwrite. Default behavior: report it and leave it untouched.
Pass --allow-corrections to actually apply those corrections — done the
same way a real moderator-approved correction would be: a NEW contribution
row is inserted (preserving the old one, and the episode's full history,
untouched) and the `episodes` row is updated to point at it as the new
current approved state. This is a deliberate, explicit opt-in specifically
because it rewrites already-published/live data, unlike a normal load.

#73/#74: each episode entry may also carry an optional "title" (episode
title, most won't have one) and "source_count" (how many independent
sources agree with this episode's status — 1 if omitted, matching the
schema default). Unlike status, these are non-contentious metadata, not a
moderation-sensitive claim, so they're synced even when the episode
already exists with a matching status (no --allow-corrections needed) —
this is what lets a show loaded before #73/#74 existed get titles/
source_count backfilled by just re-running the same JSON file. A citation
shared by several episodes (the merge_citation combo case) takes its
source_count from whichever episode first creates that combo's row; a
later episode citing the same combo with a *different* source_count is
reported, not silently overwritten, since that'd indicate the JSON itself
disagrees with itself about how many sources back a shared citation.

Every episode is loaded as an already-approved contribution
(resolution_method='moderator', submitted_by=NULL) — this is a bootstrap
import of research already vetted before being written into the JSON
file, the same provenance model load_series.py already established for
the series catalog's own bootstrap import.

Usage:
  DATABASE_URL=... python3 load_episodes.py <path-to-json>
  DATABASE_URL=... python3 load_episodes.py <path-to-json> --allow-corrections

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


def merge_citation(
    source_ids: tuple[str, ...], sources_by_id: dict
) -> tuple[str | None, str, str | None]:
    """Returns (url, description, methodology_note). #77: methodology_note
    is optional per source — a source with nothing more to say than its
    short description just omits the key, same as the episodes' own
    optional status_note.
    """
    sources = [sources_by_id[sid] for sid in source_ids]
    if len(sources) == 1:
        source = sources[0]
        return source.get("url"), source["description"], source.get("methodology_note")
    desc_parts = []
    note_parts = []
    for source in sources:
        if source.get("url"):
            desc_parts.append(f"{source['description']} ({source['url']})")
        else:
            desc_parts.append(source["description"])
        if source.get("methodology_note"):
            note_parts.append(source["methodology_note"])
    combined_note = " / ".join(note_parts) if note_parts else None
    return None, " / ".join(desc_parts), combined_note


def main() -> None:
    import psycopg2

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    allow_corrections = "--allow-corrections" in sys.argv[1:]
    if len(args) != 1:
        print(
            "Usage: DATABASE_URL=... python3 load_episodes.py <path-to-json> [--allow-corrections]",
            file=sys.stderr,
        )
        sys.exit(1)

    json_path = Path(args[0])
    data = json.loads(json_path.read_text())
    series_title = data["series_title"]
    sources_by_id = {source["id"]: source for source in data["citation_sources"]}
    episodes = data["episodes"]
    print(f"Loaded {len(episodes)} episodes for {series_title!r} from {json_path.name}")
    if allow_corrections:
        print("--allow-corrections: episodes with a differing existing status WILL be updated")

    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False
    inserted = 0
    already_present = 0
    corrected = 0
    metadata_synced = 0
    citations_inserted = 0
    citations_reused_from_db = 0
    needs_correction: list[tuple[int, str, str]] = []
    source_count_conflicts: list[tuple[int, tuple[str, ...], int, int]] = []
    failures: list[tuple[int, str]] = []
    # combo (sorted tuple of source ids) -> (citation_id, source_count).
    # Populated as combinations are encountered; each citation insert is
    # committed immediately (see below) so it survives even if a later
    # episode using the same combination fails.
    citation_by_combo: dict[tuple[str, ...], tuple[int, int]] = {}

    def get_or_create_citation(cur, combo: tuple[str, ...], source_count: int, episode_number: int) -> int:
        cached = citation_by_combo.get(combo)
        if cached is not None:
            citation_id, existing_source_count = cached
            if existing_source_count != source_count:
                source_count_conflicts.append((episode_number, combo, existing_source_count, source_count))
            return citation_id

        url, description, methodology_note = merge_citation(combo, sources_by_id)

        # #76: this in-run cache alone isn't enough — a SEPARATE script
        # invocation (e.g. a later --allow-corrections pass) starts with an
        # empty cache and would otherwise INSERT a brand-new citation row
        # for a combo this series already has one for, rather than finding
        # and reusing it. Scoped to this series specifically (via a real
        # contribution already using it), not globally — two unrelated
        # shows coincidentally sharing identical citation text shouldn't
        # get silently merged. IS NOT DISTINCT FROM for a NULL-safe match on
        # url/methodology_note (both legitimately NULL for many citations).
        cur.execute(
            """
            SELECT DISTINCT c.id, c.source_count
            FROM citations c
            JOIN contributions co ON co.citation_id = c.id
            WHERE co.series_id = %s
              AND c.description = %s
              AND c.url IS NOT DISTINCT FROM %s
              AND c.methodology_note IS NOT DISTINCT FROM %s
            """,
            (series_id, description, url, methodology_note),
        )
        nonlocal citations_inserted, citations_reused_from_db
        existing_rows = cur.fetchall()
        if existing_rows:
            citation_id, existing_source_count = existing_rows[0]
            if existing_source_count != source_count:
                source_count_conflicts.append((episode_number, combo, existing_source_count, source_count))
            citation_by_combo[combo] = (citation_id, existing_source_count)
            citations_reused_from_db += 1
            return citation_id

        cur.execute(
            "INSERT INTO citations (url, description, source_count, methodology_note) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (url, description, source_count, methodology_note),
        )
        citation_id = cur.fetchone()[0]
        # Committed on its own, independent of the contribution/episode
        # work below — so a later failure on THIS episode rolls back
        # only its own rows, never a citation another already-loaded
        # episode may also be using.
        conn.commit()
        citation_by_combo[combo] = (citation_id, source_count)
        citations_inserted += 1
        return citation_id

    try:
        with conn.cursor() as cur:
            series_id = find_series_id(cur, series_title)
            if series_id is None:
                print(f"No series found with title {series_title!r} — aborting", file=sys.stderr)
                sys.exit(1)

            for episode in episodes:
                episode_number = episode["episode_number"]
                title = episode.get("title")
                source_count = episode.get("source_count", 1)
                try:
                    cur.execute(
                        "SELECT e.status, e.title, c.source_count, e.citation_id, "
                        "c.url, c.description, c.methodology_note "
                        "FROM episodes e JOIN citations c ON c.id = e.citation_id "
                        "WHERE e.series_id = %s AND e.episode_number = %s",
                        (series_id, episode_number),
                    )
                    existing = cur.fetchone()

                    if existing is not None and existing[0] == episode["status"]:
                        already_present += 1
                        # #73/#74/#77: non-contentious metadata syncs even
                        # without --allow-corrections — status is unchanged,
                        # so this isn't a moderation-sensitive rewrite.
                        (
                            existing_title,
                            existing_source_count,
                            existing_citation_id,
                            existing_url,
                            existing_description,
                            existing_methodology_note,
                        ) = existing[1], existing[2], existing[3], existing[4], existing[5], existing[6]
                        synced = False
                        if title is not None and title != existing_title:
                            cur.execute(
                                "UPDATE episodes SET title = %s WHERE series_id = %s AND episode_number = %s",
                                (title, series_id, episode_number),
                            )
                            synced = True
                        if source_count != 1 and source_count != existing_source_count:
                            cur.execute(
                                "UPDATE citations SET source_count = %s WHERE id = %s",
                                (source_count, existing_citation_id),
                            )
                            synced = True
                        # #77: re-derive this episode's citation text from
                        # the (possibly rewritten) citation_sources and sync
                        # if it's drifted — this is what backfills the
                        # description/methodology_note split for a show
                        # loaded before #77 existed, just by re-running its
                        # JSON file.
                        combo = tuple(sorted(episode["citation_ids"]))
                        new_url, new_description, new_methodology_note = merge_citation(combo, sources_by_id)
                        if (new_url, new_description, new_methodology_note) != (
                            existing_url,
                            existing_description,
                            existing_methodology_note,
                        ):
                            cur.execute(
                                "UPDATE citations SET url = %s, description = %s, methodology_note = %s WHERE id = %s",
                                (new_url, new_description, new_methodology_note, existing_citation_id),
                            )
                            synced = True
                        if synced:
                            metadata_synced += 1
                            conn.commit()
                        continue

                    if existing is not None and not allow_corrections:
                        needs_correction.append((episode_number, existing[0], episode["status"]))
                        continue

                    combo = tuple(sorted(episode["citation_ids"]))
                    citation_id = get_or_create_citation(cur, combo, source_count, episode_number)

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

                    # A plain INSERT for a new episode row; ON CONFLICT DO
                    # UPDATE for a correction (existing is not None here only
                    # when --allow-corrections let us reach this point) —
                    # the old contribution row is left exactly as it was,
                    # so the episode's full history stays intact; only
                    # `episodes` (the CURRENT approved state) changes,
                    # exactly like a real moderator-approved correction.
                    cur.execute(
                        """
                        INSERT INTO episodes
                            (series_id, episode_number, status, status_note,
                             title, citation_id, approved_contribution_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (series_id, episode_number) DO UPDATE SET
                            status = EXCLUDED.status,
                            status_note = EXCLUDED.status_note,
                            -- A correction shouldn't blank out a title set by
                            -- an earlier load — only overwrite when this run
                            -- actually specifies one.
                            title = COALESCE(EXCLUDED.title, episodes.title),
                            citation_id = EXCLUDED.citation_id,
                            approved_contribution_id = EXCLUDED.approved_contribution_id,
                            updated_at = now()
                        """,
                        (
                            series_id,
                            episode_number,
                            episode["status"],
                            episode.get("status_note"),
                            title,
                            citation_id,
                            contribution_id,
                        ),
                    )
                    if existing is not None:
                        corrected += 1
                    else:
                        inserted += 1
                except Exception as exc:  # noqa: BLE001 - report, don't silently skip
                    conn.rollback()
                    failures.append((episode_number, str(exc)))
                    continue
                conn.commit()
    finally:
        conn.close()

    print(f"Inserted: {inserted}")
    print(f"Corrected (status changed): {corrected}")
    print(f"Already present, unchanged status ({metadata_synced} had title/source_count backfilled): {already_present}")
    # #76: split "new row inserted" from "found and reused an existing one"
    # — the old combined count didn't distinguish these, which is exactly
    # what made the duplicate-row bug invisible in the loader's own output
    # for as long as it went unnoticed.
    print(f"Citation rows inserted: {citations_inserted} (reused an existing row: {citations_reused_from_db})")
    if needs_correction:
        print(f"Needs --allow-corrections ({len(needs_correction)} episodes differ from what's live):")
        for episode_number, old_status, new_status in needs_correction:
            print(f"  - episode {episode_number}: live={old_status} proposed={new_status}")
    if source_count_conflicts:
        print(f"Source-count conflicts within this file ({len(source_count_conflicts)} — NOT applied, first value wins):")
        for episode_number, combo, existing_sc, new_sc in source_count_conflicts:
            print(f"  - episode {episode_number}, combo {combo}: citation already has source_count={existing_sc}, this episode specifies {new_sc}")
    print(f"Failures: {len(failures)}")
    for episode_number, err in failures:
        print(f"  - episode {episode_number}: {err}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
