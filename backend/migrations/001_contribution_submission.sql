-- #12: contribution/series-proposal submission endpoints, plus the #20/#21
-- schema pieces their earlier "decide only" merges documented but never
-- actually shipped as DDL. Additive only (new NOT NULL columns on tables
-- confirmed empty in production, new index) — safe per CLAUDE.md
-- Guardrails without needing a backfill.

ALTER TABLE series_proposals
    ADD COLUMN license_accepted BOOLEAN NOT NULL;

ALTER TABLE contributions
    ADD COLUMN license_accepted BOOLEAN NOT NULL;

CREATE UNIQUE INDEX contributions_one_pending_per_episode
    ON contributions (series_id, episode_number)
    WHERE review_status = 'pending';
