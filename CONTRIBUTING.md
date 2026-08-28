# Contributing

AniFillerPedia is built the same way Wikipedia is: anyone can submit a
correction, every claim needs a source, and changes go live once they're
either checked by a moderator or endorsed by enough of the community. This
page covers how to actually do that. For reading the data programmatically,
see [docs/API.md](docs/API.md) instead.

## Ways to contribute

- **Correct an episode's status** — propose that episode N of some series
  is canon, filler, or mixed (partly both), backed by a citation.
- **Submit a whole range at once** — if you already have a full (or
  partial) breakdown for an untouched or partially-researched show, submit
  canon/filler/mixed ranges for many episodes in one go instead of one at a
  time. Requires being logged in — see **Bulk submission** below.
- **Propose a series** that isn't in the catalog yet.
- **Suggest a synonym** — an alternate/dub/regional title for a series
  that's already in the catalog. Reviewed by a moderator directly (see
  **Suggesting a synonym** below) — it's too small a unit of moderation
  for the trust-weighted voting used elsewhere on this page.
- **Endorse or dispute** someone else's pending proposal, if you're
  logged in.

None of the single-episode paths above require an account — submitting
anonymously is a deliberate, supported path, not a limitation (see
**Anonymous vs. signed in** below). Everything here works through the raw
API directly; the site itself also has web forms for each of these under
a series' own page, if you'd rather not call the API by hand.

## Submitting a correction

```
POST /api/v1/contributions
Content-Type: application/json

{
  "series_id": 42,
  "episode_number": 63,
  "proposed_status": "mixed",
  "proposed_note": "Ch. 430 adapted, extended fight scene is anime-original",
  "citation": {
    "url": "https://example.com/some-episode-guide",
    "description": "Episode guide cross-referencing the manga chapter"
  },
  "license_accepted": true
}
```

- `proposed_status` is one of `canon`, `filler`, or `mixed`.
- `citation.description` is required; `citation.url` is optional (some
  sources are a book or guide with no URL — but a bare, undescribed URL
  isn't a citation on its own, so `description` always is).
- `license_accepted` is required and must be `true` on **every**
  submission, not just once at signup — see **Your submission and the
  license** below for why.
- If you're not logged in, you'll also need a Turnstile token (a
  CAPTCHA-like anti-abuse check) — logged-in submissions skip this
  entirely, since an authenticated account is already a stronger signal.

If an episode already has a pending correction, your submission gets
rejected with a `409` pointing at the existing one — endorse or dispute
that instead of creating a competing proposal. This project deliberately
keeps at most one pending proposal per episode at a time, rather than
letting several compete and split the community's attention.

### What makes a good citation

A citation should let someone else independently verify the claim: a
specific episode guide, a forum post cross-referencing manga chapters, an
official chronology guide. "I remember watching it" isn't a citation.
Prefer sources that state *why* an episode is filler/canon/mixed, not just
that it is — the reasoning is what makes a claim checkable later.

## Bulk submission

For a series where you have a real breakdown covering many episodes — the
same kind of Reddit/community range list this project's own hand-compiled
data is sourced from — submit it in one call instead of one episode at a
time:

```
POST /api/v1/series/{series_id}/contributions/bulk
Content-Type: application/json

{
  "canon_ranges": "1-44, 48-49, 52-53",
  "mixed_ranges": "45-47, 61",
  "filler_ranges": "54-60, 98-99",
  "citation": {
    "description": "Community-compiled breakdown, corroborated by a second independent thread"
  },
  "license_accepted": true,
  "dry_run": true
}
```

- Ranges use the same comma-separated, hyphen-range notation as any
  filler-guide breakdown you'd already have in hand. Any of the three
  fields may be empty, but at least one episode must be declared across
  all three combined.
- **Requires a logged-in account** — unlike the single-episode path above,
  one call here can create hundreds of pending contributions at once, so
  an anonymous submission isn't offered for this endpoint.
- The whole batch shares **one citation** — if different parts of your
  breakdown need different sources, submit them as separate smaller
  batches instead.
- An episode number that appears in more than one of the three ranges is
  rejected outright (`422`, before anything is written) — that's a
  self-contradiction in the submission, not something to guess past.
- Set `"dry_run": true` to see exactly what would happen — parsed episode
  counts per status, and which episodes (if any) would be skipped because
  someone else already has a pending contribution on them — without
  writing anything. Drop it (or set it `false`) to actually submit; every
  resulting contribution then goes through the exact same review process
  (moderator approval or community vote) as a normal single-episode one.
- A batch larger than 2000 episodes is rejected rather than partially
  processed — comfortably above the largest show loaded so far.

## Proposing a new series

```
POST /api/v1/series-proposals
Content-Type: application/json

{
  "title": "Some Show Not Yet Catalogued",
  "anilist_id": 123456,
  "justification": "Long-running series with a well-documented filler arc, per...",
  "license_accepted": true
}
```

`anilist_id`/`mal_id`/`anidb_id` are all optional but at least one helps
avoid an accidental duplicate. `justification` plays the same role a
citation does for an episode correction — say why this belongs in the
catalog, with something checkable.

## Suggesting a synonym

```
POST /api/v1/synonym-suggestions
Content-Type: application/json

{
  "series_id": 42,
  "synonym": "Some Official Dub Title",
  "note": "Official English dub title on Crunchyroll",
  "license_accepted": true
}
```

`note` is optional context for the moderator reviewing it — not a
citation; a synonym is lower-stakes than an episode filler/canon claim,
so it doesn't need a full source object the way a correction does. This
one is always resolved by a moderator directly, never by community
vote — see **How review works** below for why that split exists.

## How review works

Every submission starts `pending`. Episode corrections and series
proposals become live one of two ways:

1. **A moderator or admin approves it directly.**
2. **The community votes it through.** Any logged-in user can endorse or
   dispute a pending contribution:

   ```
   POST /api/v1/contributions/{id}/vote
   { "vote": "endorse" }
   ```

   Each vote is weighted by your own `trust_score`:

   ```
   trust_score = approved_count − rejected_count × 2
   ```

   (A "likes" term is defined in the formula for future use but isn't
   populated by anything yet — there's no likes feature in this project
   today, only endorse/dispute on pending contributions.) Once cumulative
   weighted endorsement crosses the current threshold (75), the
   contribution promotes automatically — no moderator click needed. One
   highly-trusted account's endorsement can cross that alone; several
   newer accounts' endorsements can also add up to it together. A dispute
   subtracts from the running total rather than being ignored, so a
   credibly-contested proposal doesn't get pushed through by raw
   endorsement count. You can't vote on your own submission, and each
   account gets one vote per contribution.

Check `GET /api/v1/episodes/{id}/history` to see a full paper trail for
any episode: every past proposal, who reviewed it (or that it resolved by
community vote, with no single reviewer), and every vote cast along the
way.

**Synonym suggestions are the one exception** — they're always resolved
by a moderator (or admin/owner) directly, with no community-vote path.
A suggested alternate title is a single low-stakes string with no
citation to weigh, so the full trust-weighted voting machinery above
would be disproportionate for it.

## Anonymous vs. signed in

You can submit single-episode corrections, series proposals, and synonym
suggestions without an account — that's intentional, not a gap. What
requires being signed in:

- **Voting** (endorse/dispute) — a vote's value comes from being tied to
  an accountable track record, which an anonymous submission structurally
  can't have.
- **Bulk submission** — one call can create hundreds of pending
  contributions, a materially bigger surface than a single anonymous
  correction; see **Bulk submission** above.
- **Seeing your own history** — `GET /api/v1/contributions/mine`,
  `/api/v1/series-proposals/mine`, `/api/v1/synonym-suggestions/mine`,
  and `/api/v1/contributions/mine/votes` only make sense for an
  identifiable account.

Sign in with GitHub or Discord (`GET /api/v1/auth/{provider}/authorize`).
Accounts are never merged automatically by matching email — linking a
second provider to an existing account is an explicit action you take
while already signed in, never something that happens for you. See
[docs/API.md](docs/API.md#authentication) for exactly how that redirect/
cookie flow works, and — importantly, if you're building an automated or
server-to-server integration rather than clicking through a browser —
its current limitations (no bearer-token/API-key alternative to a real
browser login today).

## Your submission and the license

The dataset is [CC BY-NC-SA 4.0](DATA_LICENSE) — free to read and reuse,
including by other trackers, as long as it's not powering a paid product
without a separate commercial agreement. `license_accepted: true` on each
submission is your agreement that your contribution is offered under
those same terms. Your username stays attached to your contributions in
the public history (this project doesn't anonymize *active* contributors
— see `GET /episodes/{id}/history`); if you delete your account later,
past contributions are preserved for the audit trail but anonymized, per
the [privacy policy](https://anifillerpedia.wiki/api/v1/privacy).

## Roles

- **Contributor** — everyone with an account. Can submit, vote, see their
  own history.
- **Moderator** — can review the pending queue directly (approve/reject).
- **Admin** — moderator privileges, plus can manage other users' roles
  (promote/demote between contributor and moderator).
- **Owner** — the project's single top tier. Only the owner can grant the
  admin role itself; nobody, including the owner, can change the owner's
  own role through the API.

Roles aren't self-service — reach out via a GitHub issue if you've been
contributing consistently and moderation queue turnaround would benefit
from another set of eyes.
