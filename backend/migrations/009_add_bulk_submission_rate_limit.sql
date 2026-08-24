-- Issue #84 — additive only (new table), fine per CLAUDE.md Guardrails
-- without needing to ask first. Run by hand against the live Postgres,
-- same as every migration in this project (see migrations/README.md).
--
-- ON DELETE CASCADE deliberately, unlike every other users(id) FK in this
-- schema (which use SET NULL to preserve audit-trail rows) — this table is
-- transient rate-limiting bookkeeping only, not part of the public record.

CREATE TABLE bulk_submission_events (
    id            BIGSERIAL PRIMARY KEY,
    submitted_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX bulk_submission_events_by_user_and_time
    ON bulk_submission_events (submitted_by, submitted_at);
