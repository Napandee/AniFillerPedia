-- Issue #85 — additive only (new nullable column), fine per CLAUDE.md
-- Guardrails without needing to ask first. Run by hand against the live
-- Postgres, same as every migration in this project (see migrations/README.md).
--
-- Holds a contributor's optional episode-range data attached to a series
-- proposal at submission time, in the exact shape services/contributions.py's
-- bulk-submission path already expects (canon_ranges/mixed_ranges/
-- filler_ranges/citation) — NULL until turned into real citations +
-- contributions rows once the proposal is approved (see
-- services/series_proposals.py's approve_series_proposal). A rejected
-- proposal just leaves this JSON sitting on the (now rejected) row —
-- nothing else ever references it, so nothing is orphaned by a rejection.

ALTER TABLE series_proposals ADD COLUMN episode_data JSONB;
