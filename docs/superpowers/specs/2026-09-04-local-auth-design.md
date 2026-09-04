# Local (email + password) authentication — design spec

Status: approved by Andreas, ready for implementation planning.
Decided: 2026-09-04, via brainstorming session.
Related: split from the same conversation as the admin-portal spec
(`2026-09-04-admin-portal-design.md`) — local auth is sequenced first
since the admin portal's own login story depends on this.

## Why

AniFillerPedia's only login mechanism today is GitHub/Discord OAuth, and
both provider apps have sat unprovisioned for weeks (issue #25) — purely
because provisioning them requires Andreas to manually visit each
provider's developer console in a browser, something that's kept getting
deferred. The practical consequence, confirmed directly during this
session's own review: `client_id` is empty in production, nobody can log
in, and the entire community trust/voting/moderation system — despite
being fully built and tested — has never been exercised by a real user.

This project has always intended a local account route alongside OAuth,
not instead of it. Building it now — while the admin portal work is
already in flight — unblocks real login (and therefore real testing of
the trust system, moderation queue, and the admin portal itself)
immediately, without waiting on #25 ever getting done.

## Scope

**In scope (v1):**
- Email + password signup and login
- Argon2id password hashing
- Reuse of the existing session-cookie mechanism (no new session model)
- Rate limiting on both signup and login
- Login page rework: local form primary, OAuth buttons secondary
- Owner/admin bootstrap via local signup (parallel to the existing
  GitHub-id bootstrap)

**Explicitly out of scope (v1) — each a real, tracked gap, not an oversight:**
- **Magic-link (passwordless) auth.** Andreas confirmed wanting this
  eventually, as a second iteration — not now. Password auth ships first.
- **Email verification and self-service password reset.** Both need real
  email-sending infrastructure, which doesn't exist anywhere in this
  project yet. Deliberately deferred rather than pulling in a new
  external dependency (a transactional email provider, another
  provisioning step) to ship v1 faster. **Real consequence accepted**: a
  user who forgets their password has no automated recovery path in v1 —
  file a follow-up issue for password-reset once real usage shows this is
  actually hurting people, not before.
- **CAPTCHA on local signup.** Cloudflare Turnstile's site key still
  isn't provisioned (#12/#20, same class of blocker as #25) — rate
  limiting is the only defense against bulk fake-account creation for
  now, consistent with this project's existing "detection not
  prevention" posture elsewhere (see #23's canary-entry approach).
  Fast-follow once Turnstile is actually live.
- **Disk-level encryption at rest.** Filed separately as issue #223 —
  a genuine, pre-existing gap (Postgres's data directory lives on the
  droplet's unencrypted local disk, not an encrypted DO Block Storage
  Volume) that applies to the whole database today, not something local
  auth introduces or makes worse. Deliberately not folded into this
  spec so it doesn't block a well-scoped feature behind a bigger
  infra migration.

## Data model

Add to the **existing** `users` table (additive migration, no data loss,
no existing row touched):

```sql
ALTER TABLE users ADD COLUMN password_hash TEXT;

-- Only local (password-having) accounts require a unique email — this
-- must NOT constrain existing OAuth-only rows, which were never
-- guaranteed unique on email and must never break.
CREATE UNIQUE INDEX users_email_unique_when_local
    ON users (email)
    WHERE password_hash IS NOT NULL;
```

`password_hash` coexists with `github_id`/`discord_id`/`google_id` on the
same row — a user can have a password *and* linked OAuth providers
simultaneously, once account linking is used. This is not a separate
"local accounts" table; it's the same `users` table gaining one more way
to authenticate.

**Real semantic change, called out explicitly**: `users.email`'s existing
schema comment says "from whichever provider supplied it; never the
login key" — written when email was purely OAuth profile metadata. For
local accounts, email *is* the login key. Update that column's comment
to reflect the dual meaning: metadata-only for OAuth-only rows, a real
credential for rows with `password_hash` set.

**Password hashing**: argon2id (the `argon2-cffi` library or equivalent),
not bcrypt. Passwords are hashed, never encrypted — hashing is one-way
and cannot be reversed even if the database and any encryption key were
both compromised, which is the correct property for credential storage
(as distinct from data that legitimately needs to be read back, like
email). No arbitrary complexity rules on the password itself beyond a
sensible minimum length (e.g. 8 characters) — modern guidance favors
length and rate-limiting over forced complexity theater.

## Auth flow

Two new endpoints, both minting the *exact same* session cookie every
OAuth login already produces (`httpOnly`, `samesite=lax`) — this is a
new way to establish a session, not a parallel session system:

- `POST /api/v1/auth/local/signup` — `{email, password, display_name}` →
  creates the account, sets `password_hash`, immediately active (no
  verification step in v1). Rejects if the email is already registered
  as a local account (the partial unique index above enforces this at
  the DB layer; the app layer turns the constraint violation into a
  friendly 409, matching this project's existing pattern for other
  uniqueness constraints).
- `POST /api/v1/auth/local/login` — `{email, password}` → verifies the
  hash, sets the session cookie on success.

**Rate limiting** (reusing `repositories/rate_limits.py` — no new rate-
limit infrastructure):
- Signup: per-IP, abuse-prevention shaped (mirrors the existing
  `contribution_submit`/`export_request_access` limits' own scale).
- Login attempts: keyed by **email + IP combined**, not IP alone — this
  slows down credential-stuffing against one targeted account without
  collateral-blocking every other login attempt from a shared IP
  (an office network, a VPN exit node, etc.).

**No CAPTCHA in v1** (see Scope above) — rate limiting is the only
defense against bulk signup abuse until Turnstile is actually live.

## Login page rework

The existing login page currently shows only "Sign in with GitHub" /
"Sign in with Discord" buttons. Rework:

- Email + password form becomes the **primary, first-visible** element.
- The existing OAuth buttons remain, fully functional, code untouched —
  just repositioned to a secondary/below position, since #25 may still
  get provisioned later and that work shouldn't be discarded or hidden
  away entirely.
- A signup/login toggle on the same page (not two separate pages) —
  the common, low-friction pattern.

## Account linking

**No new mechanism needed.** The existing `/settings/link/{provider}`
route (explicit-only linking, never auto-link by email match — an
existing hard rule this project already enforces for OAuth-to-OAuth
linking) already generalizes cleanly to "starting from a local account."
A logged-in local user reaches the same route to link a GitHub/Discord
account afterward.

## Owner/admin bootstrap

Extend the existing `INITIAL_ADMIN_GITHUB_ID` env-var pattern with a
parallel `INITIAL_ADMIN_EMAIL` — a local signup whose email matches
becomes `'owner'` on creation, identical mechanism and reasoning to the
existing GitHub-id bootstrap. This project deliberately never does
"first user becomes admin" (a real security hole on an open-signup site,
and the specific mistake this project's own design already rejected —
see CLAUDE.md's Decisions Made on the owner role tier). This is what
actually lets Andreas log in locally as owner without depending on any
OAuth provisioning ever completing.

## Testing

Real Postgres, never mocked, per this project's standing convention —
argon2id verification, the partial unique index's actual enforcement,
rate-limit behavior under repeated attempts, and the `INITIAL_ADMIN_EMAIL`
bootstrap path all need real-database tests, not unit tests against a
mocked session.

## Migration safety

Fully additive — one new nullable column, one new partial index. No
existing row is touched, no existing behavior changes for OAuth-only
accounts. Matches this project's own migration guardrail (additive
migrations don't need explicit sign-off before applying) — but given
this touches the authentication path directly, apply the standard
migrate-then-merge discipline (apply to production before the app-code
PR merges) regardless.

## Open questions

None remaining — every decision point raised during brainstorming was
resolved above. If implementation surfaces something not covered here,
treat it as new scope requiring its own quick decision, not something to
silently improvise.
