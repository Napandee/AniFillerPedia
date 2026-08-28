-- Issue #149 — a submitter can withdraw their own still-pending
-- contribution before it's resolved. Additive only (widens two existing
-- CHECK constraints, no column added, no existing row's data touched) —
-- same class of change as migration 003 (users.role gaining 'owner'), fine
-- per CLAUDE.md Guardrails to just do without asking first.
--
-- Design choice (see PR description for the full tradeoff writeup): a
-- fourth review_status value, 'withdrawn', distinct from 'rejected' —
-- preserves a real audit-trail entry showing the submitter withdrew it
-- themselves, rather than hard-deleting the row (which would lose the
-- record that a withdrawal ever happened). Consistent with this project's
-- established bias toward preserving audit trail everywhere else in the
-- schema (GDPR account-deletion decision: SET NULL anonymizes but never
-- deletes contribution/vote history).
--
-- resolution_method also gains 'withdrawn_by_submitter' — mirrors how
-- 'moderator'/'community_vote' already record *how* a contribution reached
-- its resolved state; a withdrawal is a third, distinct way one can be
-- resolved (by the submitter themselves, not a moderator or a vote).
--
-- Confirmed against a fresh install of the pre-migration schema (local
-- test-pg, 2026-08-28) that Postgres named these constraints
-- contributions_review_status_check / contributions_resolution_method_check
-- by default, matching schema.sql's own inline CHECK clauses.
--
-- contributions_one_pending_per_episode (the partial unique index scoped
-- to WHERE review_status = 'pending') is unaffected — a withdrawn row no
-- longer matches that predicate, so the submitter (or anyone else) is
-- immediately free to submit a fresh contribution for the same episode,
-- same as after a rejection.

ALTER TABLE contributions DROP CONSTRAINT contributions_review_status_check;
ALTER TABLE contributions ADD CONSTRAINT contributions_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'withdrawn'));

ALTER TABLE contributions DROP CONSTRAINT contributions_resolution_method_check;
ALTER TABLE contributions ADD CONSTRAINT contributions_resolution_method_check
    CHECK (resolution_method IN ('moderator', 'community_vote', 'withdrawn_by_submitter'));
