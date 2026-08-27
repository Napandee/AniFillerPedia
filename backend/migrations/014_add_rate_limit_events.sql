-- Issue #139/#141 — additive only (new table), fine per CLAUDE.md
-- Guardrails without needing to ask first. Run by hand against the live
-- Postgres, same as every migration in this project (see migrations/README.md).
--
-- Generic rate-limit bookkeeping for the anonymous-accessible write
-- endpoints (POST /contributions, POST /series-proposals when
-- episode_data is attached and the caller isn't logged in, and
-- POST /export/request-access) — deliberately NOT reusing #84's
-- bulk_submission_events table, since that table's `submitted_by` is a
-- NOT NULL FK to users(id) and these endpoints need to rate-limit callers
-- who have no user id at all. `identifier` is caller-supplied: a
-- "user:<id>" string when authenticated (so a shared IP/NAT never lumps
-- distinct logged-in users together) or an "ip:<address>" string
-- otherwise. `scope` keeps each endpoint's counters independent so hitting
-- one doesn't consume another's budget. No FK / no audit-trail purpose —
-- same "transient bookkeeping only" reasoning as bulk_submission_events.

CREATE TABLE rate_limit_events (
    id           BIGSERIAL PRIMARY KEY,
    scope        TEXT NOT NULL,
    identifier   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX rate_limit_events_by_scope_identifier_time
    ON rate_limit_events (scope, identifier, created_at);
