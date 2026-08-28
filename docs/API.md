# API guide

AniFillerPedia's read API is public and unauthenticated — no account, no API
key, no rate-limit wall for reasonable use. This guide covers what the raw
[OpenAPI schema](https://anifillerpedia.wiki/openapi.json) and its
[interactive docs](https://anifillerpedia.wiki/docs) don't: what the
endpoints are *for*, how the pieces fit together, and real example requests.

If you want to *submit* corrections or propose series, see
[CONTRIBUTING.md](../CONTRIBUTING.md) instead — this page is about reading
the data.

## Base URL

```
https://anifillerpedia.wiki/api/v1
```

Every endpoint below is relative to that. All responses are JSON except
`GET /privacy` (HTML).

## Authentication

**Every read endpoint in this guide (Series, Episodes, License, and the
first step of Bulk export) is public and unauthenticated.** Auth only
gates *write* actions that need an accountable identity, or ones scoped
to one caller's own data:

| Requires login | Doesn't |
|---|---|
| `POST /series/{id}/contributions/bulk` | `POST /contributions` (single-episode — anonymous allowed, see [CONTRIBUTING.md](../CONTRIBUTING.md)) |
| `POST /contributions/{id}/vote` | `POST /series-proposals` (anonymous allowed) |
| `POST /contributions/{id}/withdraw` (own pending submissions only — anonymous submissions can't be withdrawn) | |
| `GET /contributions/mine`, `/mine/votes` | `GET /series/*`, `/episodes/*` (all public reads) |
| `GET /series-proposals/mine` | `POST /export/request-access` (email-gated, not login-gated) |
| `GET /users/me`, `DELETE /users/me` | `GET /export` (API-key-gated, not login-gated) |
| `GET /settings/link/{provider}` | `GET /license`, `GET /privacy` |
| Moderator+: `GET /contributions`, `GET /series-proposals`, every `/approve`, `/reject`, `/bulk-approve`, `/bulk-reject` | |
| Admin+: `GET /admin/users`, `PATCH /admin/users/{id}/role` | |

**How the login flow actually works.** This API has exactly one auth
mechanism today: a browser-driven, cookie-based OAuth redirect. There is
**no bearer-token or API-key alternative for any of the endpoints in the
table above** — the `X-API-Key` header only exists for `GET /export`,
which is a separate, deliberately non-account-based gate (see **Bulk
export** below), not a general-purpose auth token.

1. Send the browser to `GET /auth/{provider}/authorize` (`provider` is
   `github` or `discord`), optionally with `?next=/some/path` to control
   where the browser lands afterward. This sets a short-lived,
   `httponly`/`samesite=lax` state cookie and 302s to the provider's own
   consent screen — a real user has to see and approve this screen; it
   cannot be automated headlessly against a real provider account.
2. The provider redirects back to `GET /auth/{provider}/callback`, which
   verifies the signed `state` against that cookie (real CSRF protection,
   not just a signature check — see `routers/auth.py`), exchanges the
   OAuth `code` for the provider's profile, and either logs in/creates the
   user or (if this callback is completing a `GET /settings/link/{provider}`
   flow instead) links the provider to whichever account initiated it.
3. On success, the response sets `afp_session` — an `httponly`,
   `samesite=lax`, `secure` cookie, scoped to the whole site (`path=/`) —
   and either 303-redirects to `next` or returns a plain JSON body
   directly. Every subsequent authenticated request just needs to send
   that cookie back; there's no separate token to attach to headers.
   The signed token inside the cookie stays valid server-side for 30 days,
   but the cookie itself carries no explicit browser-side expiry, so a
   real browser drops it when it closes — a consumer that wants a
   longer-lived credential would need to persist the raw cookie value
   itself, which is exactly the kind of undocumented, unsupported use this
   section is flagging rather than recommending.

**What this means for a non-browser (server-to-server) consumer** — the
concrete case this project's own `CLAUDE.md` names as the actual point of
having a public API (e.g. a future AniDex integration): **today, nothing
in the table above is realistically callable without a human completing
the OAuth consent screen at least once.** A script *can* drive the redirect
chain with an HTTP client that follows redirects and persists cookies
(`requests.Session`, `curl -c cookiejar.txt`, etc.), but step 1 above still
lands on a real provider consent page a human has to approve — there is no
client-credentials/service-account grant, no long-lived API token, and no
documented way to mint a session without that human step. In practice this
means: **build against the public read endpoints only** (everything in the
right-hand column above) for a fully automated integration today. If a
real server-to-server write use case shows up, treat adding a proper
service-account/bearer-token path as a real, scoped addition to design —
not something to work around by scripting the cookie flow against a real
human-owned account.

## Series

### Search / list series

```
GET /series?q=naruto&limit=20&offset=0
```

`q` matches against a series' title **and** its known alternate/romanized/
native-script titles — so `q=NARUTO疾風伝` and `q=naruto shippuden` can both
find the same series. You can also look up by external ID instead of text:
`anilist_id`, `mal_id`, or `anidb_id`.

**A plain call with no `q` and no external id excludes series with zero
episode rows.** Most of the catalog was bootstrap-imported from an open
dataset that carries no per-episode data at all — showing those alongside
researched shows made the default browse list mostly empty pages. A
*targeted* lookup (`q`, or any of the three external ids) still returns a
zero-episode series if it matches, so you can find an existing catalog
entry — and its real `series_id` — before proposing what would otherwise
be a duplicate. `GET /series/{series_id}` and its `/episodes` are
unaffected either way: a zero-episode series is still a normal 200 with an
empty episode list if you already have its id.

```json
{
  "items": [
    { "id": 42, "anilist_id": 1735, "mal_id": 1735, "anidb_id": null,
      "title": "Naruto: Shippuden", "provenance": "manami_bootstrap",
      "created_at": "2026-08-20T12:00:00Z",
      "slug": "naruto-shippuuden",
      "cover_image_url": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx1735.jpg",
      "banner_image_url": "https://s4.anilist.co/file/anilistcdn/media/anime/banner/1735.jpg",
      "airing_status": "FINISHED",
      "sequence_order": 2 }
  ],
  "total": 1, "limit": 20, "offset": 0
}
```

`slug` (#116) is null only for the small window before the one-time
production backfill ran — everything created since always has one.
`cover_image_url`/`banner_image_url` (synced from AniList by a daily
worker, not fetched live) and `airing_status` (#111 — AniList's own
`MediaStatus`: `FINISHED`, `RELEASING`, `NOT_YET_RELEASED`, `CANCELLED`,
`HIATUS`) are both null until that worker has synced this series at least
once. `sequence_order` (#133) is null for the vast majority of series —
only set for entries that are part of a multi-entry franchise group (see
`related_series`/`next_series`/`previous_series` below) with a decided
watch order.

Add `sort=recently_updated` to order by which series had an episode's
status most recently approved, instead of the default insertion order —
useful for a "recently updated" list.

### Get one series

```
GET /series/{id_or_slug}
```

`{id_or_slug}` accepts either the numeric `id` from a search result above,
or the `slug` (#116) — both resolve indefinitely, so a client can rely on
either form as a stable identifier. Response is the same shape as a search
result, plus:

```json
{
  "id": 42, "anilist_id": 1735, "mal_id": 1735, "anidb_id": null,
  "title": "Naruto: Shippuden", "provenance": "manami_bootstrap",
  "created_at": "2026-08-20T12:00:00Z",
  "slug": "naruto-shippuuden",
  "cover_image_url": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx1735.jpg",
  "banner_image_url": "https://s4.anilist.co/file/anilistcdn/media/anime/banner/1735.jpg",
  "airing_status": "FINISHED",
  "sequence_order": 2,
  "synonyms": ["NARUTO疾风伝", "Naruto Hurricane Chronicles"],
  "anilist_episode_count": 500,
  "related_series": [
    { "id": 41, "title": "Naruto", "slug": "naruto", "sequence_order": 1, "...": "..." }
  ],
  "description": "Naruto Uzumaki, is a loud, hyperactive, adolescent ninja...",
  "start_date": "2007-02-15", "end_date": "2017-03-23",
  "next_series": null,
  "previous_series": { "id": 41, "title": "Naruto", "slug": "naruto", "sequence_order": 1, "...": "..." }
}
```

- `synonyms` — the full list of alternate/romanized/native-script titles
  matched by search.
- `anilist_episode_count` — AniList's own real total episode count,
  independent of how many of them this project has actually researched
  (compare against the length of `GET /{id}/episodes`'s response). Null
  until the sync worker has reached this series.
- `related_series`/`next_series`/`previous_series` (#59/#133) — lightweight
  links to other catalog entries covering the same underlying show split
  across multiple real AniList entries (e.g. Fairy Tail / Fairy Tail
  (2014) / Fairy Tail (2018), each a separate catalog row a filler guide
  numbers continuously). `next_series`/`previous_series` are the immediate
  neighbors by `sequence_order` within that group; both null for the vast
  majority of series with no such grouping. `related_series` items are
  full `SeriesOut` objects — the shortened form above elides fields already
  shown on the parent object.
- `description`/`start_date`/`end_date` (#126) — AniList's own synopsis and
  air-date range, only exposed on this detail response (not the browse/
  search list). Null until synced, or if this series predates a later
  finished-before-#126-existed backfill pass.

**Conditional requests (#155)**: this endpoint and the episodes list below
return an `ETag` and `Last-Modified` header on every `200`. Send a matching
`If-None-Match` (preferred) or `If-Modified-Since` on a later poll to get a
bare `304 Not Modified` instead of the full body — useful for a consumer
polling for changes (e.g. a future AniDex integration) rather than
re-fetching everything on a schedule.

### List a series' episodes

```
GET /series/{series_id}/episodes
```

Returns every episode this project has *researched* — there's no row for
an episode nobody's looked into yet, so absence means "no data," not
"canon by default." Episode numbering is absolute (Naruto: Shippuden goes
1–500, not restarting per season). Each entry:

```json
{
  "id": 501, "series_id": 42, "episode_number": 15,
  "status": "filler", "status_note": null, "title": "The Rain of Konoha",
  "citation": { "id": 88, "url": null,
    "description": "Community-compiled breakdown, corroborated by a second independent thread",
    "source_count": 2,
    "methodology_note": "Anime-original arc, per animenewsnetwork.com episode guide" },
  "updated_at": "2026-08-21T09:00:00Z", "aired_at": "2007-04-12T00:00:00Z",
  "has_pending_contribution": false
}
```

`status` is always one of `canon`, `filler`, or `mixed`. `citation` is
never null — nothing in this dataset is live without a source (see
[DATA_LICENSE](../DATA_LICENSE) and the project's own guardrails on this).
`citation.source_count` is how many independent sources agree (1 when
nothing corroborates it beyond the citation itself); `methodology_note` is
the fuller research trail behind that citation and is often null. `title`
and `aired_at` are both frequently null — most episodes don't have a
title yet, and `aired_at` depends on an AniList sync that doesn't reach
every episode of an older, already-finished show. `has_pending_contribution`
(#87) is a browsing affordance, not a new approval path — `true` means
this episode currently has a pending contribution awaiting review/votes
(see **Community voting** below); #20's one-pending-per-episode rule means
it's never more than a single pending item at a time.

## Episodes

### Get one episode

```
GET /episodes/{episode_id}
```

Same shape as one entry from the episodes list above.

### Full contribution history for an episode

```
GET /episodes/{episode_id}/history
```

Every proposed status change ever submitted for this episode — not just
the current approved one. Each entry includes the submitter (or `null` for
an anonymous or since-deleted-and-anonymized account — the two look
identical on purpose, see the privacy policy), the citation, the review
outcome, and any community votes cast on it:

```json
[
  {
    "id": 900, "proposed_status": "mixed",
    "proposed_note": "Ch. 421–423 adapted, ending scene is anime-original",
    "citation": { "id": 88, "url": null, "description": "..." },
    "submitted_by": { "id": 7, "display_name": "kabuto_scrolls", "github_id": "..." },
    "submitted_at": "2026-08-21T08:00:00Z",
    "review_status": "pending", "resolution_method": null,
    "reviewed_by": null, "reviewed_at": null, "review_note": null,
    "votes": [
      { "voter": { "id": 12, "display_name": "sasori_fan", "github_id": "..." },
        "vote": "endorse", "weight_at_vote": 61, "created_at": "2026-08-21T08:10:00Z" }
    ]
  }
]
```

A `pending` entry with no moderator action yet can still resolve on its
own — see **Community voting** below.

## Community voting

Any logged-in user can endorse or dispute a pending contribution:

```
POST /contributions/{contribution_id}/vote
Content-Type: application/json
{ "vote": "endorse" }
```

Each vote is weighted by the voter's own track record (their `trust_score`
— see [CONTRIBUTING.md](../CONTRIBUTING.md) for the formula), snapshotted
at the moment they vote so a later change to their trust score never
rewrites an already-resolved contribution's history. Once cumulative
weighted endorsement crosses a threshold (currently 75), the contribution
auto-promotes into the live episode data — no moderator click required.
One sufficiently-trusted voter's endorsement can cross the threshold
alone; several lower-trust voters' endorsements can also combine to.

## Bulk export

Every endpoint above is free and unauthenticated. The one exception is a
full dataset dump, because a silent anonymous bulk download has much
weaker "they agreed to the license" standing than an explicit click-through
does:

```
POST /export/request-access
{ "email": "you@example.com", "license_accepted": true }
```

Returns a one-time API key — **it's shown exactly once and can't be
retrieved again**, store it. Then:

```
GET /export
X-API-Key: <your key>
```

Returns every series and episode, plus an embedded attribution manifest
(license name, attribution notice, commercial-licensing contact) baked
into the payload — a downloaded file is disconnected from these live docs,
so it carries its own copy of that information.

Done with the key, or want the email behind it forgotten? Revoke it
yourself, no approval step:

```
POST /export/revoke
X-API-Key: <your key>
```

204 on success. Possessing the key is the only proof of identity this
needs — the same as using it to call `/export` at all. This also deletes
the email address you provided at `/export/request-access` (see the
[privacy policy](/api/v1/privacy) for why that's collected and how long
it's normally kept).

## License

```
GET /license
```

Structured JSON stating the dataset license (**CC BY-NC-SA 4.0** — free to
read and reuse non-commercially with attribution; a paid product needs a
separate commercial agreement, see [DATA_LICENSE](../DATA_LICENSE)) and
where to reach out about commercial use. The code powering this API is
separately licensed [MIT](../LICENSE) — the split matters, see
`DATA_LICENSE`'s own explanation of why.

## Errors

Standard HTTP status codes. The [OpenAPI schema](https://anifillerpedia.wiki/openapi.json)
declares the real, specific error cases per route (visible in
[/docs](https://anifillerpedia.wiki/docs) under each endpoint's "Responses"
section) — this section covers what's worth knowing beyond that.

Unless otherwise noted, an error body is `{"detail": "<message>"}`. A few
endpoints use a structured (non-string) `detail` instead, always because
the caller needs more than a message to act on it — noted below.

- **401** when an endpoint requires login and no valid session cookie was
  sent (`GET /users/me`, anything moderator/admin-gated, etc. — see
  **Authentication** above for the full list), or when `GET /export`/
  `POST /export/revoke` are called with a missing or invalid/revoked
  `X-API-Key`.
- **403** when the session cookie is valid but the account's role isn't
  high enough (e.g. a contributor hitting a moderator-only route, or an
  admin — not the owner — trying to grant the `admin` role), or when
  voting on your own submitted contribution (`POST /contributions/{id}/vote`).
- **404** on a genuinely missing resource (`series_id`, `episode_id`,
  `contribution_id`, `series_proposal_id` that doesn't exist), or an
  unrecognized `review_status` query value on the moderation-queue
  listings (only `pending` is meaningful today).
- **409** when a write conflicts with existing state — e.g. submitting a
  correction for an episode that already has a pending one (the response
  body's `detail` is an object, `{"message": "...", "existing_contribution_id": <id>}`,
  so you can endorse/dispute it instead of creating a competing
  submission), voting twice on the same contribution, approving/rejecting
  something that's no longer pending, or approving a series proposal whose
  external ID (`anilist_id`/`mal_id`/`anidb_id`) collides with an
  already-bootstrapped series.
- **400** specifically on `POST /export/request-access` when
  `license_accepted` isn't `true` — note this is the one submission-style
  endpoint that uses 400 rather than 422 for that same check (an existing
  inconsistency across the API, not a documentation error).
- **422** on a request that fails validation (missing required field, bad
  enum value, a bulk range submission that's malformed/self-contradictory/
  oversized), or on `POST /contributions`/`POST /series-proposals` when
  `license_accepted` isn't `true` — the body follows FastAPI's standard
  validation-error shape for a pure schema failure, or a plain
  `{"detail": "..."}` for a business-rule check like `license_accepted`.
- **429** on the handful of rate-limited endpoints (anonymous/bulk
  contribution submission, series-proposal submission, export key
  requests, the AniList-lookup proxy) — the body names the limit and
  window, e.g. `"You've made 6 contribution submissions in the last hour
  (limit 5)."`
