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

## Series

### Search / list series

```
GET /series?q=naruto&limit=20&offset=0
```

`q` matches against a series' title **and** its known alternate/romanized/
native-script titles — so `q=NARUTO疾風伝` and `q=naruto shippuden` can both
find the same series. You can also look up by external ID instead of text:
`anilist_id`, `mal_id`, or `anidb_id`.

```json
{
  "items": [
    { "id": 42, "anilist_id": 1735, "mal_id": 1735, "anidb_id": null,
      "title": "Naruto: Shippuden", "provenance": "manami_bootstrap",
      "created_at": "2026-08-20T12:00:00Z" }
  ],
  "total": 1, "limit": 20, "offset": 0
}
```

Add `sort=recently_updated` to order by which series had an episode's
status most recently approved, instead of the default insertion order —
useful for a "recently updated" list.

### Get one series

```
GET /series/{series_id}
```

Same shape as a search result, plus `synonyms` (the full list of alternate
titles matched by search).

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
  "status": "filler", "status_note": null,
  "citation": { "id": 88, "url": null,
    "description": "Anime-original arc, per animenewsnetwork.com episode guide" },
  "updated_at": "2026-08-21T09:00:00Z"
}
```

`status` is always one of `canon`, `filler`, or `mixed`. `citation` is
never null — nothing in this dataset is live without a source (see
[DATA_LICENSE](../DATA_LICENSE) and the project's own guardrails on this).

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
Authorization: Bearer <your key>
```

Returns every series and episode, plus an embedded attribution manifest
(license name, attribution notice, commercial-licensing contact) baked
into the payload — a downloaded file is disconnected from these live docs,
so it carries its own copy of that information.

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

Standard HTTP status codes. A few worth knowing about specifically:

- **404** on a genuinely missing resource (`series_id`, `episode_id`,
  `contribution_id` that doesn't exist).
- **409** when a write conflicts with existing state — e.g. submitting a
  correction for an episode that already has a pending one (the response
  body points you at the existing pending contribution's id so you can
  endorse/dispute it instead of creating a competing submission), or
  voting twice on the same contribution.
- **422** on a request that fails validation (missing required field, bad
  enum value) — the body follows FastAPI's standard validation-error shape.
