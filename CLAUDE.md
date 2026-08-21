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
  ruled out the most complete existing filler-list site).
- Pulling from Simkl's catalog/discovery API without their explicit prior
  permission — their own published rules restrict catalog use to apps that
  also integrate Simkl login/sync, which this project does not (see
  Guardrails).
- Being a personal watch tracker (status, progress, ratings, personal notes)
  — that's a different product; AniDex already does this for its own users
  and is explicitly not the thing this project extends or depends on.
- Monetization/paywall — the owner's explicit intent is a freely-usable
  public resource.

## Data Source

No single upstream system of record (unlike AniDex, which treats AniList as
its system of record). This project's data is bootstrapped from multiple
legitimate sources, deliberately not from one restricted site:

- **Series-level targeting signal**: the `"has fillers"` / `"canon filler"`
  tags in [manami-project/anime-offline-database](https://github.com/manami-project/anime-offline-database)
  (ODbL-licensed, genuinely open) — used to identify *which* shows are worth
  researching in detail, not as a source of per-episode data (it has none).
  **One-time bootstrap import only, not a live dependency**: confirmed
  2026-08-20 that the upstream repo is archived (last release `2026-27`,
  2026-07-04) — the ODbL license means the last snapshot stays permanently
  reusable, but there's no active maintainer to keep pulling updates from.
  The `series` catalog is seeded once from that snapshot and grows afterward
  entirely through community series-proposal submissions (see Data Model) —
  it is not an auto-synced/rebuildable table the way AniDex's AniList-sourced
  tables are.
- **Per-episode data**: hand-compiled, cited research per show — reading
  public sources (wiki prose, forum discussions, official chronology guides)
  and cross-referencing multiple sources rather than trusting one, the same
  way a human editor building this by hand would. Not an automated scrape of
  any single site's database.
- **Ruled out, with reasons** (don't re-litigate these without new
  information): animefillerlist.com (no API, ToS explicitly forbids
  scraping); Simkl's catalog API (restricted to Simkl-integrating apps per
  their own published rules, without explicit permission); Jikan/unofficial
  MAL API (has real filler/recap fields, but MAL's own terms prohibit using
  it to populate a separate database); TheTVDB (paywalled since 2020, and its
  filler data — if any — traces back to Anime Filler List anyway, not TVDB's
  own); TMDB (no filler/canon field exists at all); Wikipedia's
  Wikidata/episode-list articles (checked directly for several confirmed
  "has fillers" shows — no per-episode filler/canon signal exists there
  either, contrary to what might be assumed).

## Data Model

Not yet built. Known requirements, to get right from the start:

- Separate the episode-level community-contributed/correctable layer
  (filler/canon status, source citations) from the series catalog — but note
  the series catalog itself is *not* an auto-synced/rebuildable table the way
  AniDex's AniList-sourced tables are (manami-project's dataset is archived,
  see Data Source), so it's bootstrapped once and then grown the same way
  episode data grows: community proposal + approval, never an unmoderated
  direct write.
- Every entry needs a status (pending/approved) and a citation — no entry
  should be live/authoritative without both a source and at least one
  approval, given the "Wikipedia-style, not open-write" model this project is
  built around.
- An audit trail of who submitted/approved/corrected what — needed for the
  approval-flow model to actually mean something.

## Architecture

Not yet built, but the shape is decided (2026-08-20 planning session):

- **API**: FastAPI, `/api/v1/...`, layered routers/services/repositories.
  Public read endpoints (series, episodes, per-episode citation, per-episode
  contribution history) are unauthenticated. Contribution/series-proposal
  submission requires GitHub OAuth login (any contributor); approval/rejection
  requires moderator/admin role. Same API serves both the public Astro
  frontend (via a typed client generated from FastAPI's own OpenAPI schema)
  and any external consumer (e.g. a future AniDex integration) — one contract,
  no separate internal API.
- **Async/side-effects**: transactional outbox pattern, not a message broker.
  An `outbox_events` table is written to in the same DB transaction as any
  state change other systems care about (contribution submitted/approved/
  rejected, series proposal submitted/approved). A separate lightweight
  worker container polls it (`FOR UPDATE SKIP LOCKED`) and dispatches side
  effects (moderator Telegram notification on new pending contribution,
  Cloudflare cache purge on approval so public pages refresh immediately
  rather than waiting on a cache TTL). Postgres is the broker — no Redis/
  Celery. Chosen deliberately over waiting to add this later: the
  write-path/schema stay unchanged if real scale ever justifies swapping the
  poller for a heavier Postgres-backed queue library or running more worker
  replicas — only the consumer side would change.
- **Frontend**: Astro, server-rendered (SSR/on-demand) for series/episode
  pages rather than a full static prebuild — avoids needing any
  rebuild-trigger pipeline to propagate approved changes; freshness instead
  comes from the outbox-driven cache purge above. Islands for auth, search,
  the contribution submission form, and the moderator approval-queue view.

## Deploy

Not yet decided.

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

## Decisions Made

- **Repo structure: monorepo** (`backend/` FastAPI + `frontend/` Astro in
  one repo), decided 2026-08-21. Deciding factors: the typed-client codegen
  pipeline (openapi-typescript against FastAPI's OpenAPI schema) is a local
  file read in a monorepo versus real cross-repo fetch/auth complexity in a
  split; and 23 issues already existed on one roadmap board by this point —
  splitting would have fragmented planning work already done, not just
  future work. **Rejected**: separate repos (`AniFillerPedia` +
  `AniFillerPedia-web` or similar) — real advantages considered (contributor
  clarity per side, reads more clearly as "the API is a standalone product"
  to external consumers, cleaner mapping if frontend ever hosts somewhere
  different like Cloudflare Pages) but doubled ops surface (two self-hosted
  runners, two secret sets, two `pr-validate.yml`s) and the schema-fetch
  complexity weren't worth it for a solo/small-team-maintained project.
  Note even the "different host" advantage doesn't actually require a
  split — Cloudflare Pages can build from a subdirectory of a monorepo
  directly. The monorepo choice is only safe because of the hard
  backend/frontend separation enforced in Guardrails — treat that
  enforcement as load-bearing, not optional.
- **License**: split — [CC BY-NC-SA 4.0](DATA_LICENSE) for the dataset
  itself, [MIT](LICENSE) for code. The data/code split still matches the
  *structural* precedent set by manami-project/anime-offline-database (one
  of this project's own seed sources); code stays GPL-3.0-free/MIT
  regardless of the dataset license.
  **Changed 2026-08-20 from the original ODbL v1.0 choice.** ODbL was
  initially picked over CC0 for its attribution + share-alike terms, but the
  owner's actual intent — established the same day — is stricter than
  share-alike: no paywalled/paid product may use this data as a backing
  source without a separate commercial agreement, and ODbL has no
  non-commercial clause at all, so this required a re-license, not a text
  edit. Landed on CC BY-NC-SA 4.0 + an explicit "contact us for a commercial
  license" carve-out over two alternatives: hand-written custom legal text
  (rejected — real enforceability risk without a lawyer drafting it) and
  staying on ODbL with a bolted-on restriction (not possible — the clause
  doesn't exist in that license family). Known tradeoff, accepted knowingly:
  CC licenses don't cover EU Sui Generis Database Rights as specifically as
  ODbL does. **The restriction is on *use*, not *contribution*** — anyone
  may contribute corrections/citations/proposals regardless of employer;
  what needs an agreement is consuming the data (API, bulk export, or
  otherwise) to power a product that charges its own end users. See
  `DATA_LICENSE` for the full text and the commercial-licensing note.
  **Not yet lawyer-reviewed** — same honesty flag as the rest of this
  project's license reasoning (see issue #21): treat as a considered,
  good-faith position, not confirmed legal advice, until a real review
  happens before public launch.
- **Standalone from AniDex, not a feature of it**: this started as a spike
  inside AniDex (issue #161, "filler episode tracking") but was deliberately
  split into its own project rather than built as an AniDex feature — the
  owner's explicit intent is a freely-usable public resource other trackers
  could also consume, not something scoped to one personal instance's users.
  AniDex may become a *consumer* of this project's API later, but that's a
  separate future decision, not assumed here.
- **Tech stack**: FastAPI (Python) + Postgres (SQLModel + SQLAlchemy 2.0 Core
  where needed) + Astro frontend (islands for auth/search/submission-forms/
  approval-queue), typed API client generated from FastAPI's own OpenAPI
  schema via `openapi-typescript` + `openapi-fetch`, GitHub OAuth via FastAPI
  Users. Deploy: DigitalOcean Droplet, GitHub Actions builds/pushes to GHCR,
  a self-hosted runner on the droplet pulls and restarts — same
  build-then-self-hosted-runner-deploys pattern as `Napandee/AniDex`, no
  webhook/n8n hop. Decided 2026-08-20.
- **Series catalog is community-grown, not auto-synced**: seeded once from
  manami-project's archived last snapshot, then extended only via a
  `series_proposals` approval flow (mirrors episode `contributions`) — never
  an unmoderated direct write, and never a recurring external sync since
  there's no longer an active upstream to sync from. Decided 2026-08-20.
- **Episode status/numbering**: three values only — `canon` / `filler` /
  `mixed` (a `recap` value was considered and deliberately dropped — not
  worth the added distinction). Episode numbering is absolute (matches how
  filler guides count, e.g. Naruto: Shippuden 1–500), not per-season.
  Structured (non-freeform) citation data for `mixed` episodes — e.g. a
  manga chapter range or scene/timestamp range instead of prose — is
  deliberately deferred, tracked as
  [issue #2](https://github.com/Napandee/AniFillerPedia/issues/2), Held on
  the roadmap board. `status_note` ships as freeform text in v1 regardless.
- **Auth: GitHub + Discord OAuth at launch; Google added separately, not
  launch-blocking.** Originally decided 2026-08-20 as "all three at launch,"
  **reversed 2026-08-21** once the practical consequence sank in: Google's
  OAuth app needs to pass Google's verification review to leave "Testing"
  mode (a 100-user cap otherwise), which depends on a privacy policy
  existing, which depends on the account-deletion/data-retention decisions
  in #18 — a real dependency chain with no fixed timeline. Bundling Google
  into "launch" meant launch was implicitly gated on that whole chain
  finishing. GitHub and Discord have no such dependency. Google OAuth is now
  tracked as its own separable, non-blocking addition — see the issue
  filed 2026-08-21 for it. Reuses `Napandee/AniDex`'s already-proven
  multi-provider pattern regardless of provider count: explicit-only account
  linking (never auto-link by email match — a provider-supplied email isn't
  proof of identity; linking only via an authenticated
  `/settings/link/{provider}` route, separate from ordinary login).
  **Differs from AniDex on admin bootstrap**: AniDex's first-user-becomes-
  admin is a real security hole for a public open-signup site (whoever signs
  up first — or after any future DB reset — gets admin) — use an env var
  (e.g. `INITIAL_ADMIN_GITHUB_ID`) checked against identity on first login
  instead.
- **Contribution model allows anonymous submission**, approved by one of two
  paths: moderator approval (human backstop, always available), or a
  **community trust-weighted vote** — any logged-in user can endorse/dispute
  a pending contribution, weighted by their own `trust_score`; once
  cumulative weighted endorsement crosses a threshold, it auto-promotes
  with no moderator click needed (one sufficiently-trusted user's single
  vote can cross the threshold alone, or several lower-trust users' votes
  can combine to). `trust_score` is anchored primarily to track record, not
  raw likes (likes are gameable via sockpuppets; "past submissions verified
  correct" isn't): `approved_count + likes_received × small_weight −
  rejected_count × penalty`, with rejection costing more than approval earns
  to discourage low-effort spam — exact weights/threshold still tunable,
  not finalized. Schema: `contributions.submitted_by` becomes nullable,
  gains `resolution_method` (`'moderator'` | `'community_vote'`); new
  `contribution_votes` table (`contribution_id`, `voter_id`, `vote`
  endorse/dispute, `weight_at_vote` — snapshotted so later trust changes
  don't rewrite resolved history, one vote per user per contribution).
  **Known open gap**: anonymous submission removes the natural
  per-identity rate limit — needs a basic anti-abuse layer (e.g. Cloudflare
  edge rate-limiting on the anonymous submission endpoint specifically)
  before launch, not yet designed in detail.
- **Cloudflare Turnstile on the anonymous submission endpoint** (decided
  2026-08-21, issue #20) — free, privacy-friendly, trivial given the
  project is already fully on Cloudflare. Scoped narrowly: the anonymous
  contribution-submission path specifically (the one path with literally
  no identity behind it), and worth extending to signup/login too since
  it doubles as a cheap first line of defense against the Sybil-farming
  concern already flagged for #14. Deliberately NOT on read endpoints
  (undermines the no-rate-limit-wall goal) or authenticated submissions
  (OAuth login is already a stronger signal than a CAPTCHA).
- **At most one pending contribution per episode** (decided 2026-08-21,
  issue #20) — a new submission targeting an `(series_id, episode_number)`
  that already has a `pending` contribution is rejected (409), pointing
  the submitter at the existing pending contribution's id so they endorse/
  dispute it instead of creating a competing row. Rejected alternative:
  letting multiple competing pending contributions coexist and letting
  voting sort it out — rejected because it risks vote-splitting (two
  reasonable claims each stall below threshold instead of one clearly
  succeeding), muddles the audit trail (whose citation actually informed
  the final call), and doesn't match the single-current-draft model most
  wiki-style systems use. Enforced structurally, not just in application
  code: a partial unique index,
  `UNIQUE (series_id, episode_number) WHERE review_status = 'pending'` —
  consistent with this project's preference for DB-level guarantees over
  policies to remember. Resolves #20's own open question about whether the
  vote threshold applies per-contribution independently: moot now, since
  there's never more than one pending contribution per episode to split
  votes across. Moderation-queue implication: a moderator/voter always
  sees exactly one pending item per episode, not several to reconcile.
- **GDPR / account deletion** (decided 2026-08-21, issue #18) — confirms
  and finalizes what #6's schema already shipped provisionally:
  `ON DELETE SET NULL`, uniformly, on every FK referencing `users`
  (`series.added_by`, `contributions.submitted_by`/`reviewed_by`,
  `citations.submitted_by`, `series_proposals.submitted_by`/`reviewed_by`,
  `contribution_votes.voter_id`) — including votes, resolving #18's own
  open question about whether votes should behave differently: no,
  because `contribution_votes.weight_at_vote` is already snapshotted at
  vote time (see the trust-voting decision above), so a resolved
  contribution's tally stays intact even once the voter's identity is
  nulled — anonymizing loses *who*, never the *evidence* the audit trail
  needs. **Account deletion is self-service**, not admin-mediated: a
  `DELETE /api/v1/users/me` a user can call on their own account, no
  admin approval gate. Reasoning: this is public open signup, not
  AniDex's small invite-only pool — routing every deletion through an
  admin doesn't scale for a solo maintainer and risks slow turnaround on
  what GDPR expects to be a reasonably prompt right, and since `SET NULL`
  already anonymizes rather than erasing the audit trail, self-service
  deletion can't be used to hide misconduct — the contribution/vote
  content stays, only the PII (email, display name, avatar, OAuth ids)
  goes. **Data-retention statement** (feeds #19's privacy policy
  directly): *"Deleting your account removes your personal data (email,
  display name, avatar, linked sign-in identifiers) immediately. Your
  past contributions and votes are preserved but anonymized — they
  remain part of the public record and audit trail, which a
  community-maintained database depends on, but are no longer linked to
  your identity. Deleted personal data may persist in backups for up to
  14 days"* (a real number, not invented — matches #10's actual shipped
  `scripts/backup-postgres.sh` retention window).
- **CC BY-NC-SA mechanics** (decided 2026-08-21, issue #21) — three parts:
  1. **Contributor licensing**: every single contribution (not "once at
     signup") carries structural proof of agreement — a `license_accepted`
     boolean, `NOT NULL`, on the row itself, mirroring how `citation_id
     NOT NULL` already enforces the citation guardrail structurally rather
     than trusting app-layer discipline. Chosen over a one-time
     account-level acceptance specifically because anonymous submission
     (no persistent identity to attach a one-time flag to) has to be
     per-submission anyway — making authenticated contributions follow the
     identical rule is one uniform rule to build and reason about instead
     of two, and it's a lightweight checkbox on the form each time, not a
     legal-text re-read.
  2. **API attribution**: a dedicated `GET /api/v1/license` endpoint
     (structured JSON — license name, attribution notice, commercial
     contact) plus FastAPI's own `license_info` field on the `FastAPI(...)`
     app object, so it surfaces automatically in the OpenAPI schema `/docs`
     and to anything consuming that schema (including #11's typed-client
     codegen) — chosen over embedding a `license` field in every single
     response object, which would repeat static metadata on every request
     for no real benefit. The bulk export (#22) is different: a downloaded
     file is disconnected from live API docs, so it needs its own embedded
     attribution manifest baked into the export payload itself, not just a
     reference to the docs.
  3. **Commercial-licensing contact**: `licensing@anifillerpedia.wiki`,
     proposed and written into `DATA_LICENSE` — not yet confirmed live,
     flagged there for Andreas to set up mail routing or swap in a real
     channel. No standard commercial-license template exists yet; each
     inquiry gets negotiated individually until real demand justifies
     building one — consistent with this project's general bias against
     building for demand that doesn't exist yet.
