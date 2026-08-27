-- Issue #126 — additive only (new nullable columns), fine per CLAUDE.md
-- Guardrails without needing to ask first. Run by hand against the live
-- Postgres, same as every migration in this project (see migrations/README.md).
--
-- Adds AniList's own description (synopsis) and air-date range to the
-- series row, synced by #49's existing daily worker (services/anilist_sync.py)
-- alongside the fields it already fetches (status, episode count, cover/
-- banner art) — no new job, same cadence. anilist_start_date/anilist_end_date
-- are only ever set when AniList's own {year, month, day} is fully complete
-- for that field (never a partial/fabricated date) — an ongoing/RELEASING
-- show simply has a NULL anilist_end_date, same "store nothing rather than
-- a placeholder" convention used throughout this project.
--
-- All three columns start NULL and are backfilled gradually by the
-- existing sync worker's normal cadence — no backfill script needed here.

ALTER TABLE series ADD COLUMN anilist_description TEXT;
ALTER TABLE series ADD COLUMN anilist_start_date DATE;
ALTER TABLE series ADD COLUMN anilist_end_date DATE;
