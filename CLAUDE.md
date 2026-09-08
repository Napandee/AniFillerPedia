# AniFillerPedia — Project Context for Claude Code

## Purpose

An open, community-editable database of anime filler/canon episode data — which
episodes are anime-original ("filler") versus adapted from the source manga
("canon"), with mixed episodes flagged separately. It exists because no
existing option is both genuinely open (free to read, free to contribute to,
no ToS wall) and API-accessible (see Guardrails — the two closest existing
sources each fail one of those). Standalone project, not part of AniDex — see
Decisions Made for why.

**Open for reading and contributing; not for powering paid products without
agreement** (decided 2026-08-20, see Decisions Made — License): anyone may
read the data or contribute corrections/citations/new-series proposals,
regardless of who they work for — an employee of a commercial, paid anime
tracker is as welcome to contribute as anyone else. What requires a separate
commercial agreement is *using* this project's data (via the API, a bulk
export, or otherwise) as a backing data source for a product or service that
charges its own end users. Contribution and consumption are governed
differently on purpose.

## Scope

**In scope:**
- Per-episode filler/canon/mixed status for anime series, not just a
  series-level "this show has filler" flag.
- A public, unauthenticated read API — no account, no sync requirement, no
  rate-limit wall for reasonable use.
- A community correction workflow (submit/adjust/correct entries) gated by an
  approval flow — not open unmoderated write access.
- A source citation per entry, so every filler/canon claim is traceable to
  where it came from.

**Out of scope — do not build these:**
- Scraping any site whose terms of service forbid it (see Guardrails — this
  ruled out animefillerlist.tv specifically; see Data Source below for why
  that's a distinct question from animefillerlist.com, the actually
  long-established, more complete site of the two — evaluated separately
  in issue #48 and deliberately not pursued as a source either, for
  reasons unrelated to `.tv`'s ToS).
- Pulling from Simkl's catalog/discovery API without their explicit prior
  permission — their own published rules restrict catalog use to apps that
  also integrate Simkl login/sync, which this project does not (see
  Guardrails).
- Being a personal watch tracker (status, progress, ratings, personal notes)
  — that's a different product; AniDex already does this for its own users
  and is explicitly not the thing this project extends or depends on.
- Monetization/paywall — the owner's explicit intent is a freely-usable
  public resource.

## Deploy

Decided 2026-08-20, live since 2026-08-21. DigitalOcean Droplet running
`backend`/`frontend`/`worker`/`postgres`/`caddy` containers; GitHub Actions
builds and pushes to GHCR on a merge to `master`, path-filtered separately
for `backend/**` and `frontend/**` per the monorepo split above; a
self-hosted runner container on the droplet itself pulls the new image and
restarts (`docker compose pull` + `up -d`) — no webhook, no HMAC, no
inbound SSH hop. Same build-then-self-hosted-runner-deploys pattern as
`Napandee/AniDex`. See Decisions Made — Tech stack for the original
decision record.

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
- **Monorepo with a hard backend/frontend split, not a shared tangle.**
  `backend/` (FastAPI/Python) and `frontend/` (Astro/Node) live in one repo
  (decided 2026-08-21 specifically to keep the roadmap board and the
  typed-client codegen pipeline simple — see Decisions Made) but must stay
  genuinely separate: no dependency files, configs, or tooling bleeding
  across the two directories. CI must use path-based triggers
  (`paths: ['backend/**']` / `paths: ['frontend/**']`) so a change on one
  side never rebuilds or redeploys the other. This is what makes the
  monorepo choice safe rather than a shortcut to coupling them — don't
  quietly erode it for convenience.
- **Stay stateless — no local-disk dependencies for anything that persists
  or that other requests rely on.** The droplet-based deploy (decided
  2026-08-21, see Decisions Made) is deliberate, not a technical necessity —
  the app layer itself should stay portable to a serverless target (Cloud
  Run, etc.) even though that's not the current plan. The concrete case to
  watch: the bulk `/export` dump (#7/#22) must use object storage (DO
  Spaces or Cloudflare R2, both S3-compatible) rather than local disk on
  the droplet. Local disk breaks under any future stateless/scale-to-zero
  deploy target; object storage doesn't, and costs nothing extra to use
  from the start. No in-memory state that other requests or instances
  depend on, either.

## Where the detail lives

Read these when the task calls for them — they are not loaded by default.

- `docs/architecture.md` — before changing how backend, frontend or database fit together.
- `docs/data-model.md` — when touching schema, episode status values, or series records.
- `docs/data-sources.md` — before adding or changing a scraper or import path.
- `docs/decisions.md` — before proposing anything that changes licensing, auth,
  the contribution model, or the episode status vocabulary. Fifteen decisions
  with their reasoning; check it before re-litigating one.
- `docs/API.md` — the HTTP API surface.
