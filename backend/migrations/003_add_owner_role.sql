-- Adds the 'owner' role tier (decided 2026-08-21, see CLAUDE.md Decisions
-- Made) on top of the existing contributor/moderator/admin roles. Widens
-- the existing CHECK constraint only — no column added, no data touched,
-- no existing row's role value changes as a result of running this.
--
-- Postgres names an inline column CHECK constraint <table>_<column>_check
-- by default, which is what schema.sql's original `role TEXT ... CHECK
-- (...)` produced — confirmed against a fresh install of the pre-migration
-- schema before writing this.
--
-- Does NOT retroactively promote anyone to 'owner' on the live droplet DB
-- — the existing bootstrapped admin (INITIAL_ADMIN_GITHUB_ID) keeps role
-- 'admin' until manually updated once, after this migration is applied:
--   UPDATE users SET role = 'owner' WHERE github_id = '<the real owner's github id>';
-- Deliberately not scripted here — a manual, explicit step for a
-- one-person action, not something to automate into a migration file.

ALTER TABLE users DROP CONSTRAINT users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('contributor', 'moderator', 'admin', 'owner'));
