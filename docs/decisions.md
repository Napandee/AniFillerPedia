# Decisions

Architectural decisions and why they were made. Each entry states the decision,
the date, and the issue it came from. Entries are appended, not rewritten — a
superseded decision is marked superseded rather than deleted.

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
  correct" isn't): originally specified as `approved_count + likes_received
  × small_weight − rejected_count × penalty`, but no `likes` mechanism
  exists anywhere in the schema — the shipped formula
  (`services/admin.py::compute_trust_score`) is
  `approved_count − rejected_count × REJECTION_PENALTY`, with the likes
  term simply never implemented (the code's own docstring discloses this;
  this doc previously didn't, which was the actual gap — noted 2026-09-03
  after an independent review caught the drift). Rejection costs more than
  approval earns, to discourage low-effort spam — exact weights/threshold
  still tunable, not finalized. Schema: `contributions.submitted_by` becomes nullable,
  gains `resolution_method` (`'moderator'` | `'community_vote'`); new
  `contribution_votes` table (`contribution_id`, `voter_id`, `vote`
  endorse/dispute, `weight_at_vote` — snapshotted so later trust changes
  don't rewrite resolved history, one vote per user per contribution).
  **Known open gap**: anonymous submission removes the natural
  per-identity rate limit — needs a basic anti-abuse layer (e.g. Cloudflare
  edge rate-limiting on the anonymous submission endpoint specifically)
  before launch, not yet designed in detail.
- **#14 (community trust-weighted voting) implemented** (2026-08-21) —
  `POST /api/v1/contributions/{id}/vote` (any logged-in user; anonymous
  voting is NOT offered, unlike submission, since a vote's whole value is
  being weighted by an accountable `trust_score`). Auto-approval threshold
  shipped as `75` — a starting default, not a tuned number (still
  explicitly tunable per the trust-voting decision above), chosen to match
  the "3 endorse · trust 61/75" figure already used as the illustrative
  example in this project's own UI mockups rather than inventing an
  unrelated number. `weight_at_vote` is the voter's `trust_score` at cast
  time, floored at 0 (a negative `trust_score` is meaningful at the
  user-record level, but a negative-weighted vote would invert its own
  polarity in the endorse-minus-dispute net-score sum). Two additions
  beyond #14's written scope, both judged necessary rather than optional:
  a submitter cannot vote on their own pending contribution (403 —
  otherwise any submitter with a positive `trust_score` could self-endorse
  toward the threshold), and dispute votes subtract from net score rather
  than being ignored, so credible disputes can hold off a promotion that
  endorsements alone would otherwise cross. **Sybil-resistance decision**
  (#14's own flagged open question): accepted as a documented v1
  limitation, not engineered around further — no real abuse data exists
  yet to weigh the rate-limiting/tenure-weighting/correlation-heuristic
  alternatives against, matching this project's general bias against
  building for demand that doesn't exist yet. The one mitigation already
  shipped is incidental, not built for this: Turnstile on the anonymous
  submission endpoint (below) raises the cost of farming the
  `approved_count` history a sockpuppet would need in the first place.
  Revisit with a real design pass if real abuse is observed post-launch,
  not before.
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
- **Owner role tier, distinct from admin** (decided 2026-08-21, issue #28,
  during Phase 5 planning) — the existing two-tier model (moderator/admin)
  let any admin promote/demote anyone else to any role, including minting
  other admins; on a public open-signup site that's a real
  privilege-escalation surface, not just a UI nuance. `users.role` gains a
  fourth value, `'owner'`, strictly above `'admin'` (each tier a superset
  of the one below, matching the existing admin-is-a-superset-of-moderator
  pattern). Only the owner can grant the `'admin'` role; the owner's own
  row can never be changed via the role-promotion endpoint, by anyone,
  including themselves. `'owner'` is deliberately excluded from the
  promotable-roles list entirely — never assignable through the API, set
  once at bootstrap (`INITIAL_ADMIN_GITHUB_ID` now grants `'owner'`, not
  `'admin'`) and otherwise only changeable via a manual, one-time DB
  update, matching the deliberate manual-not-automated stance already
  taken on GDPR deletion's retention window. **Rejected**: treating
  "owner" as purely cosmetic (the bootstrap identity keeps role `'admin'`,
  with no structural distinction) — the simpler option, but it leaves the
  privilege-escalation gap open the moment a second admin exists, which
  Phase 5's admin UI is expected to make easy to create.
- **CORS: deliberately left unconfigured** (decided 2026-08-27, issue
  #142) — no `CORSMiddleware` in `backend/main.py`, and that's a decision,
  not an oversight. No real external browser-based consumer exists today:
  the Astro frontend calls this API same-origin (Caddy splits
  `/api/v1/*` to the backend container on the same domain, never a
  cross-origin browser-JS call), and auth is cookie-based session tokens
  (`samesite=lax`, `httpOnly`) — which wouldn't usefully support
  cross-origin browser calls without meaningfully more work (a bearer-
  token auth path, explicit origin allowlisting, credentialed-CORS
  wiring) even if CORS were opened. The one speculative future consumer
  named elsewhere in this doc (a possible AniDex integration) would most
  plausibly be server-to-server, which CORS doesn't gate at all — it's a
  browser-enforced restriction, so a server calling this API directly is
  unaffected by CORS being closed either way. **Rejected**: opening CORS
  now for anticipated future consumers with no concrete one yet — this
  project's own general bias (stated repeatedly elsewhere in this doc) is
  against building for demand that doesn't exist yet, and a wide-open
  `allow_origins=["*"]` would be actively worse than the current default
  for zero present benefit. Revisit if a real browser-based third-party
  client actually shows up wanting cross-origin reads — at that point,
  scope any opening to the public read endpoints specifically (series/
  episodes/citations), not the auth-gated write paths, and treat it as a
  real (if small) architecture change requiring the same care as any
  other Guardrails-listed decision, not a quick middleware add.

## Visual direction — DECIDED (2026-08-21): Playful Fandom

**Locked in: canvas theme "03 · Playful fandom"** — bold color, diagonal
energy, Baloo 2 (display) + Nunito (body), pink/coral accent (#d6337a) on a
warm cream background. Chosen from the three finalists (03 Playful fandom,
08 Glossy modern SaaS, 10 Soft pastel) explored 2026-08-20. This was
originally "deliberately deferred, not made" pending Phase 2–4 backend work
— that deferral is now resolved; treat this as final unless Andreas
explicitly reopens it.

Canvas: https://claude.ai/code/artifact/2809d89e-1bd3-4374-a9ab-d6c03f226a91
(private artifact — not for the public repo's `CLAUDE.md`, hence living
here). The canvas's "Interactive demo" page has a clickable Playful Fandom
prototype (home → series → back) if a live feel is needed again later.
Don't confuse canvas "theme 03" with GitHub **issue #3** ("community
correction queue design") — unrelated, coincidental numbering.

**Update 2026-08-22: Phase 5 has actually started.** The three blockers
noted below (as of the 2026-08-21 planning pass) are all resolved — kept
struck-through rather than deleted, for the historical trail:
- ~~The real UX pass never written to any file~~ — captured across the 11
  filed Phase 5 issues (#31–#41) instead of a separate doc.
- ~~Board Theme field has no "Frontend & UX" option~~ — added same day.
- ~~No Phase 5 GitHub issues exist yet~~ — #31–#41 filed 2026-08-21.

**#31 (scaffold) shipped 2026-08-22**, commit `3a2a0c3`: `frontend/` is now
a real Astro app (SSR, `@astrojs/node` standalone adapter), the Playful
Fandom tokens/components below are implemented in
`frontend/src/styles/tokens.css` + `frontend/src/components/`, and #11's
typed client is wired into a real page (`index.astro` calls the backend's
`/api/v1/health` server-side). Verified end-to-end with a real HTTP server,
not just type-checked. `frontend-validate.yml` CI added (path-filtered,
mirrors the backend's `pr-validate.yml`). #32–#41 build on this shell next.

- **Local email+password authentication, alongside OAuth, not instead of
  it** (decided 2026-09-04, issue #224) — GitHub/Discord OAuth stayed the
  only way to log in for weeks with #25's OAuth apps unprovisioned, which
  meant nobody could actually log in to production or exercise the trust/
  voting/moderation system end to end. Adds email+password signup/login
  (argon2id hashing) as a fully first-class second path, reusing the
  existing session-cookie mechanism rather than a parallel auth scheme:
  `users.password_hash` (nullable, coexists with the OAuth id columns —
  additive migration `021_add_local_auth.sql`), `/login` renders the local
  form as primary with OAuth buttons secondary, and a new
  `INITIAL_ADMIN_EMAIL` bootstrap variable parallels the existing
  GitHub-id-based one. Rate-limited on both signup and login, reusing
  existing rate-limit infrastructure rather than a new mechanism.
  Explicitly deferred: magic-link auth, email verification, password
  reset, CAPTCHA on this specific flow (disk-level encryption tracked
  separately as #223). Full design:
  `docs/superpowers/specs/2026-09-04-local-auth-design.md`.
- **Admin portal, gated by role, not a security boundary in the UI
  itself** (shipped #234, shield placement corrected #235) — a shared
  `AdminLayout.astro` tab strip (Moderation for moderator/admin/owner,
  Users/Traffic for admin/owner only) consolidates what were previously
  scattered top-level pages (`/moderation` → `/admin/moderation`, a 301
  redirect kept at the old path) under `/admin/*`. The header's admin
  shield icon is a navigation affordance only — every actual permission
  check happens server-side per endpoint, same as before; the shield's
  role-gating in the frontend just avoids showing the entry point to
  users who'd get a 403 anyway. Corrected 2026-09-04 after initial
  placement read as visually out of place: moved to sit last inside
  `<nav>` (the true right edge, matching `Napandee/AniDex`'s own
  placement) with sizing/styling matching the header's existing
  `.nav-toggle`/`.lang-trigger` icon-button pattern, rather than sitting
  inline mid-nav.
- **Traffic dashboard shows real numbers, not a black box, and documents
  its own limits in-page** (shipped #236) — the admin traffic page
  (`/admin/traffic`, gated admin/owner) renders #221's daily Cloudflare
  Analytics rollups as a log-scaled world map (156-country SVG, tooltips
  via `Intl.DisplayNames`) plus summary stats, and ships its own
  `<details>` "About this data" panel spelling out exactly what's
  collected, known shortcomings, and what extending it further would cost
  in privacy-policy/retention terms — rather than presenting the numbers
  with no context on what they do and don't represent. Deliberately
  scoped to the existing Cloudflare Analytics aggregate rollups only, not
  raw per-request Caddy log ingestion (`/data/access.log` on the droplet
  already retains raw IP+path+timestamp data independent of this
  feature — see the privacy-policy honesty gap this surfaced, tracked
  separately).
  **Addendum, 2026-09-10 (issue #250):** extended with bot/human traffic
  classification, hourly rollups, and an abuse-signal panel — prompted by
  a real question (a large volume of requests toward the login endpoint,
  investigated and resolved as well-known crawlers, chiefly Facebook's
  link-preview bot, following the "Log in" nav link's per-page `next=`
  URL on every crawled page — not credential stuffing; the real
  `POST /auth/local/login` endpoint saw 3 hits in 9 days). Bot
  classification is a maintained `userAgent` token list applied to the
  same Cloudflare-sourced aggregate this page already used — **not**
  Cloudflare Bot Management, confirmed live via a direct GraphQL query
  against this zone that this plan does not have access to the
  `botScore` dimension. Hourly rollups are a second table
  (`traffic_hourly_rollups`) with a 7-day retention window (pruned every
  cycle) rather than the daily table's unlimited history — different
  purpose, recent-detail investigation vs. long-term trend, so a
  different retention policy on purpose. The rate-limit-activity panel
  reads `rate_limit_events`, a table that already existed for enforcing
  this app's own rate limits — a new view onto existing data, not a new
  collection mechanism, so none of this required a privacy-policy change
  or a Cloudflare plan upgrade.
