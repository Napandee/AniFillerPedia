-- Issues #20 and #21 — decided 2026-08-21 (see CLAUDE.md Decisions Made)
-- but never actually landed in schema.sql until now, found while building
-- #22 (which needs license_accepted to exist). Additive only (new
-- NOT NULL columns need a default for existing rows — there are none yet
-- in production for either table, so this is safe to run as-is; if that
-- ever changes before this runs, backfill first).

ALTER TABLE contributions ADD COLUMN license_accepted BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE contributions ALTER COLUMN license_accepted DROP DEFAULT;

ALTER TABLE series_proposals ADD COLUMN license_accepted BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE series_proposals ALTER COLUMN license_accepted DROP DEFAULT;

CREATE UNIQUE INDEX contributions_one_pending_per_episode
    ON contributions (series_id, episode_number)
    WHERE review_status = 'pending';
