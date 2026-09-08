# AniFillerPedia — Project Context for Claude Code

## Purpose

An open, community-editable database of per-episode anime filler/canon status
(`canon` / `filler` / `mixed`). No existing option is both genuinely open and
API-accessible. Standalone project, **not** part of AniDex.

**Contribution and consumption are governed differently on purpose:** anyone may
read or contribute. Backing a product that charges its end users needs a separate
commercial agreement. Reasoning in `docs/decisions.md`.

## Scope

**In scope:** per-episode status (not a series-level flag); a public
unauthenticated read API; a moderated correction workflow; a citation per entry.

**Out of scope — do not build these:**
- Scraping any site whose ToS forbids it. Ruled out animefillerlist.tv;
  animefillerlist.com was evaluated and also not pursued — `docs/data-sources.md`.
- Simkl's catalog API without explicit prior permission — their rules restrict it
  to apps that also integrate Simkl login/sync.
- A personal watch tracker. Different product; AniDex does that.
- Monetization or a paywall.

## Deploy

Merge to `master` builds and ships to the live droplet automatically. Pipeline,
runner and repo-variable detail is private — `.claude/context/deploy.md`,
gitignored because this repo is public.

## Guardrails — Non-Negotiable

- Track bugs, enhancements, and research spikes as GitHub issues (use
  `.github/ISSUE_TEMPLATE/task.md`) before starting work on them, not just in
  commit messages or chat — the reasoning needs to be findable later without
  digging through history. When work starts: assign the issue to the repo
  owner (`gh issue edit <n> --add-assignee Napandee`) and reference it in the
  eventual commit(s) with a closing keyword (`Fixes #n` / `Closes #n`) so it
  auto-closes on merge.
- Merge multi-commit feature branches with a real merge commit
  (`gh pr merge --merge`), not squash — pass the flag explicitly.
- Never commit secrets, tokens, or API keys. Env vars only — never hardcoded,
  never logged.
- **Never scrape a site whose terms of service forbid it, and never use a
  throwaway/anonymous account specifically to make a ToS-restricted action
  harder to trace back.** If a data source's terms require asking first
  (e.g. Simkl's), that means actually asking — via a real, attributable
  request — not finding a way around needing to ask. This is the whole
  reason this project's initial data comes from hand-compiled, cited research
  rather than any single scraped or API-restricted source.
- Community-submitted corrections require an approval flow before becoming
  live/authoritative — never wire up direct unmoderated public writes to the
  dataset, even for a "small trusted community" framing. This is a
  structural guarantee, not a policy to remember to enforce manually.
- Ask before any schema migration that could drop or alter existing
  columns/data — additive migrations (new nullable column, new table) are
  fine to just do.
- Ask before changing the deploy pipeline once one exists — changes there
  affect the live deployment path.
- **Monorepo with a hard split per component, not a shared tangle.**
  `backend/` (FastAPI/Python), `frontend/` (Astro/Node), and `mcp/` (Python,
  the read-only MCP server, added 2026-08-27 issue #159/#178) live in one
  repo (decided 2026-08-21 specifically to keep the roadmap board and the
  typed-client codegen pipeline simple — see `docs/decisions.md`) but must stay
  genuinely separate: no dependency files, configs, or tooling bleeding
  across directories. CI must use path-based triggers (`paths:
  ['backend/**']` / `paths: ['frontend/**']` / `paths: ['mcp/**']`) so a
  change to one never rebuilds or redeploys another. This is what makes the
  monorepo choice safe rather than a shortcut to coupling them — don't
  quietly erode it for convenience.
- **Stay stateless — no local-disk dependencies for anything that persists
  or that other requests rely on.** The droplet-based deploy (decided
  2026-08-21, see `docs/decisions.md`) is deliberate, not a technical necessity —
  the app layer itself should stay portable to a serverless target (Cloud
  Run, etc.) even though that's not the current plan. The concrete case to
  watch: the bulk `/export` dump (#7/#22) must use object storage (DO
  Spaces or Cloudflare R2, both S3-compatible) rather than local disk on
  the droplet. Local disk breaks under any future stateless/scale-to-zero
  deploy target; object storage doesn't, and costs nothing extra to use
  from the start. No in-memory state that other requests or instances
  depend on, either.

## Where the detail lives

Read when the task calls for them — not loaded by default.

- `docs/decisions.md` — before changing licensing, auth, the contribution model,
  or the status vocabulary. Check it before re-litigating a decision.
- `docs/architecture.md` — before changing how backend, frontend and database fit together.
- `docs/data-model.md` — schema, status values, series records.
- `docs/data-sources.md` — before adding or changing a scraper or import path.
- `docs/API.md` — the HTTP API surface.
- `docs/FAULTS.md` — what has gone wrong here before, and the guard each
  fault produced.
