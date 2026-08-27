-- Issue #116 — additive only (new nullable, unique column), fine per
-- CLAUDE.md Guardrails without needing to ask first. Run by hand against
-- the live Postgres, same as every migration in this project (see
-- migrations/README.md).
--
-- Slug-based series URLs (/series/berserk instead of /series/8). Nullable
-- until backfilled — the companion 011_backfill_series_slugs.py must be
-- run immediately after this migration, against the same database, before
-- any code depending on a populated slug goes live (repositories/series.py's
-- lookup falls back to slug only when the path segment isn't purely
-- numeric, so an unbackfilled NULL slug just means that series is only
-- reachable by its numeric id for a while, not a hard failure).
--
-- Collision disambiguation for duplicate-title-derived slugs (e.g. "Fairy
-- Tail" / "Fairy Tail (2014)" / "Fairy Tail (2018)") happens in
-- application code (services/slugs.py), not here — this migration only
-- adds the column + uniqueness constraint that makes a silent collision
-- impossible to write in the first place.

ALTER TABLE series ADD COLUMN slug TEXT UNIQUE;
