-- #209: account-suspension mechanism (ToS/acceptable-use enforcement).
-- Additive only — two nullable columns, no backfill needed since NULL is
-- the correct default (active) for every existing row.
--
-- Numbered 019, not 018: a concurrent, unrelated migration
-- (018_backend_integrity_bundle.sql, #184/#194/#195/#204) was mid-flight
-- in this same working tree while this one was being written — same
-- migration-number-collision class of issue CLAUDE.local.md's "Process
-- lessons: parallel-agent batches" entry already documents. Re-verify the
-- real next free number on origin/master immediately before applying
-- this to production, in case ordering has shifted by then.
--
-- suspended_at is the single source of truth for suspended/active state
-- (NULL = active, set = suspended) rather than a separate boolean that
-- could drift from it — same "one source of truth" preference as the rest
-- of this schema (see e.g. contributions.review_status/resolution_method).
-- suspended_reason is a moderator-facing note, cleared whenever a
-- suspension is lifted.
ALTER TABLE users ADD COLUMN suspended_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN suspended_reason TEXT;
