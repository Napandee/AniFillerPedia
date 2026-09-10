# Traffic Dashboard v2 — Design

## Motivation

Prompted by a real question: Andreas noticed a large volume of requests
toward the login endpoint and asked whether it was credential stuffing.
Investigating required an ad-hoc SSH session and manual Caddy-log grepping
to find the answer (it wasn't — see below). The admin traffic dashboard
(`/admin/traffic`, shipped #221/#236) already existed but couldn't have
answered this question on its own: it has no per-path *investigation* view
beyond a top-15 table, no way to tell bot traffic from real visitors, no
granularity finer than a day, and nothing surfacing the app's own
rate-limit signal. This spec closes those four gaps using data sources
already available — no new privacy-policy change, no Cloudflare plan
upgrade.

**What the investigation actually found** (context for why the design
below is shaped the way it is): of ~24,000 auth-path requests over 9 days,
only 3 hit the real `POST /api/v1/auth/local/login` endpoint. The rest
were `meta-externalagent` (Facebook/Instagram/WhatsApp's link-preview
crawler, ~21.5k), Amazonbot, GPTBot, Googlebot, and SemrushBot following
the "Log in" nav link — which every page renders with a `next=<current
page>` query param, so a full-site crawl naturally produces one distinct
`/login` and `/api/v1/auth/{provider}/authorize` URL per page crawled.
Confirmed via Cloudflare's own GraphQL Analytics API that this zone's plan
does **not** have Bot Management (`botScore` dimension access denied), but
**does** expose `userAgent` and `datetimeHour` dimensions on the existing
`httpRequestsAdaptiveGroups` dataset already queried by #221's rollup —
both verified live against production, not assumed from documentation.

## Goals

1. Per-path breakdown — already shipped (`top_paths`); no change needed.
2. Bot vs. non-bot traffic split, derived from `userAgent` via a
   maintained pattern list. Framed honestly as "known_bot" vs. "other" —
   this is a heuristic classifier, not a claim of certainty about what
   "other" traffic actually is.
3. Hourly rollups (in addition to the existing daily ones), for recent
   spike investigation — a real reason a moment like today's question
   would be answerable from the dashboard itself, not just from live logs.
4. An abuse-signal panel sourced from the existing `rate_limit_events`
   table (already collected for rate-limiting; zero new privacy cost).

## Non-goals

- No raw Caddy log ingestion, no per-visitor/per-request storage of any
  kind. Everything here stays aggregate, matching the existing dashboard's
  privacy posture — see its own "About this data" panel's reasoning for
  why that line is deliberate, not accidental.
- No Cloudflare plan upgrade / Bot Management — the classifier is a
  self-maintained User-Agent pattern list, not Cloudflare's own bot score.
- No city/region-level geography — still country-only, unchanged from
  today (Cloudflare doesn't expose finer geography to this plan either).
- Hourly rollups get a **7-day retention window** (pruned after each
  cycle), not indefinite history — daily rollups keep unlimited history as
  today. Different purpose: hourly is for "what just happened," daily is
  for "how has this trended."

## Architecture

```
Cloudflare GraphQL Analytics API (httpRequestsAdaptiveGroups)
        │  (existing daily query + new userAgent dimension)
        ▼
services/traffic_analytics.py
  ├─ classify_bot(user_agent) -> "known_bot" | "other"      [new, pure]
  ├─ aggregate_rollup(groups) -> {..., bot_breakdown}        [extended]
  ├─ run_daily_traffic_rollup()                              [extended: passes bot_breakdown]
  └─ run_hourly_traffic_rollup()                             [new: 1h window, own loop]
        │
        ▼
repositories/traffic_analytics.py
  ├─ upsert_daily_rollup(..., bot_breakdown)                 [extended]
  ├─ upsert_hourly_rollup(...)                                [new]
  ├─ list_hourly_rollups(...)                                 [new]
  └─ prune_hourly_rollups_older_than(cutoff)                  [new]
        │
        ▼
Postgres: traffic_daily_rollups.bot_breakdown (new column)
          traffic_hourly_rollups (new table, 7-day retention)

rate_limit_events (existing table, already populated by every rate-limited
endpoint) ──▶ repositories/rate_limits.py: list_recent_grouped(window)  [new]
                  ──▶ services/admin.py: get_rate_limit_summary()        [new]
                        ──▶ routers/admin.py: GET /admin/rate-limit-summary [new]

Both new + extended data flow into:
routers/admin.py: GET /admin/traffic (extended response), GET /admin/traffic/hourly (new)
        │
        ▼
frontend/src/pages/admin/traffic.astro (extended: bot split, hourly section, abuse panel)
```

## Components

### 1. Migration `backend/migrations/022_add_traffic_bot_and_hourly_rollups.sql`

Additive only, per Guardrails.

```sql
ALTER TABLE traffic_daily_rollups
    ADD COLUMN bot_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE traffic_hourly_rollups (
    id                SERIAL PRIMARY KEY,
    rollup_hour       TIMESTAMPTZ NOT NULL UNIQUE,
    total_requests    INTEGER NOT NULL,
    top_paths         JSONB NOT NULL,
    status_breakdown  JSONB NOT NULL,
    top_countries     JSONB NOT NULL,
    bot_breakdown     JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX traffic_hourly_rollups_rollup_hour_desc ON traffic_hourly_rollups (rollup_hour DESC);
```

Rows persisted before this migration runs get `bot_breakdown = []` by the
column default — the dashboard renders that exactly like any other
"no data recorded" case already handled (empty list, not an error).

### 2. `backend/services/traffic_analytics.py`

**`classify_bot(user_agent: str | None) -> str`** — new, pure, unit-tested
directly. Returns `"known_bot"` if the (case-insensitive) user agent
string contains any of a maintained set of known crawler tokens, else
`"other"`. `None`/empty input is `"other"`.

```python
_KNOWN_BOT_TOKENS = (
    "meta-externalagent", "facebookexternalhit", "googlebot", "bingbot",
    "gptbot", "chatgpt-user", "oai-searchbot", "amazonbot", "semrushbot",
    "ahrefsbot", "yandexbot", "duckduckbot", "applebot", "petalbot",
    "mj12bot", "dotbot", "bytespider", "claudebot", "anthropic-ai",
    "ccbot", "ia_archiver",
)

def classify_bot(user_agent: str | None) -> str:
    if not user_agent:
        return "other"
    lowered = user_agent.lower()
    return "known_bot" if any(token in lowered for token in _KNOWN_BOT_TOKENS) else "other"
```

**`_QUERY`** — add `userAgent` to the `dimensions` block (already confirmed
available live on this zone/plan; `datetimeHour` also confirmed available
but not needed in the daily query — only the new hourly query below uses
it for its own window math, not as a GROUP BY dimension, since each hourly
fetch already scopes its own `since`/`until` to one hour).

**`aggregate_rollup(groups, ...)`** — extend to also build `bot_breakdown`:
add a `bot_counts: dict[str, int]` alongside the existing
`path_counts`/`status_counts`/`country_counts`, keyed by
`classify_bot(dimensions.get("userAgent"))`, summed the same way, emitted
as `[{"category": "known_bot"|"other", "count": int}, ...]` — both
categories always present (even if one is 0), unlike the top-N-truncated
fields, since there are only ever two categories and a caller reading
`bot_breakdown[0]` shouldn't have to guess which one is missing.

**`run_daily_traffic_rollup()`** — pass `rollup["bot_breakdown"]` through
to `upsert_daily_rollup` alongside the existing three fields. No other
change; still a 24h window, still once/day by default interval.

**`run_hourly_traffic_rollup() -> bool`** — new, mirrors
`run_daily_traffic_rollup()` structurally but: `since = until -
timedelta(hours=1)`; persists via `upsert_hourly_rollup` keyed by
`rollup_hour=until.replace(minute=0, second=0, microsecond=0)`; after a
successful persist, calls `prune_hourly_rollups_older_than(session,
cutoff=until - timedelta(days=settings.traffic_hourly_rollup_retention_days))`
in the same transaction. Same missing-token no-op convention as the daily
function (shares the same `_logged_missing_token`-style guard, but its own
module-level flag so the two loops' log-once behavior doesn't interfere).

**`run_hourly_traffic_rollup_forever()`** — new, same
try/except-log-and-continue-forever shape as
`run_traffic_rollup_forever()`, paced by
`settings.traffic_hourly_rollup_interval_seconds`.

### 3. `backend/repositories/traffic_analytics.py`

- `upsert_daily_rollup(...)` — add `bot_breakdown: list[dict]` parameter,
  included in the `INSERT ... ON CONFLICT DO UPDATE` alongside the
  existing three JSONB columns (same `json.dumps` binding convention).
- `upsert_hourly_rollup(session, *, rollup_hour, total_requests, top_paths, status_breakdown, top_countries, bot_breakdown) -> None`
  — same shape as `upsert_daily_rollup`, `ON CONFLICT (rollup_hour) DO UPDATE`.
- `list_hourly_rollups(session, limit: int = 48) -> list[Row]` — most
  recent `limit` hours, newest first (default 48 = two days' worth,
  comfortably inside the 7-day retention window).
- `prune_hourly_rollups_older_than(session, cutoff: datetime) -> None` —
  `DELETE FROM traffic_hourly_rollups WHERE rollup_hour < :cutoff`.

### 4. `backend/repositories/rate_limits.py`

New function, additive (existing `count_recent`/`record` untouched):

```python
async def list_recent_grouped(
    session: AsyncSession, *, window_hours: int, limit: int
) -> list[Row]:
    """Per (scope, identifier) counts within the window, most-active
    first — the abuse-signal dashboard panel's data source. A window scan
    over an already-indexed, append-only table (rate_limit_events_by_
    scope_identifier_time), same cost class as the per-scope count_recent()
    query this module already runs constantly for live rate-limiting.
    """
    result = await session.execute(
        text(
            """
            SELECT scope, identifier, count(*) AS event_count,
                   min(created_at) AS first_seen, max(created_at) AS last_seen
            FROM rate_limit_events
            WHERE created_at > now() - make_interval(hours => :window_hours)
            GROUP BY scope, identifier
            ORDER BY event_count DESC
            LIMIT :limit
            """
        ),
        {"window_hours": window_hours, "limit": limit},
    )
    return list(result.fetchall())


async def count_recent_totals(session: AsyncSession, *, window_hours: int) -> Row:
    """Headline numbers for the same window: total events and distinct
    identifiers, regardless of the LIMIT applied to list_recent_grouped's
    per-identifier detail above — so a summary sentence like "143 events
    across 12 identifiers" stays accurate even when the detail table below
    it is truncated to the top 25.
    """
    result = await session.execute(
        text(
            """
            SELECT count(*) AS total_events, count(DISTINCT identifier) AS distinct_identifiers
            FROM rate_limit_events
            WHERE created_at > now() - make_interval(hours => :window_hours)
            """
        ),
        {"window_hours": window_hours},
    )
    return result.one()
```

### 5. `backend/schemas/admin.py`

```python
class TrafficBotEntryOut(BaseModel):
    category: str = Field(description="'known_bot' or 'other' — a heuristic User-Agent classification, not a certainty claim")
    count: int

# TrafficRollupOut gains:
    bot_breakdown: list[TrafficBotEntryOut]

class TrafficHourlyRollupOut(BaseModel):
    rollup_hour: str
    total_requests: int
    top_paths: list[TrafficPathEntryOut]
    status_breakdown: list[TrafficStatusEntryOut]
    top_countries: list[TrafficCountryEntryOut]
    bot_breakdown: list[TrafficBotEntryOut]
    created_at: str

class TrafficHourlyRollupListOut(BaseModel):
    items: list[TrafficHourlyRollupOut]

class RateLimitEventSummaryEntryOut(BaseModel):
    scope: str
    identifier: str
    count: int
    first_seen: str
    last_seen: str

class RateLimitSummaryOut(BaseModel):
    window_hours: int
    total_events: int
    distinct_identifiers: int
    top_entries: list[RateLimitEventSummaryEntryOut]
```

### 6. `backend/services/admin.py`

- `list_traffic_rollups(...)` — map `row.bot_breakdown` into
  `TrafficRollupOut` the same way the other three fields already are.
- `list_hourly_traffic_rollups(session, limit: int) -> TrafficHourlyRollupListOut`
  — same mapping shape as the daily equivalent, new function.
- `get_rate_limit_summary(session, *, window_hours: int, limit: int) -> RateLimitSummaryOut`
  — calls `rate_limits_repo.list_recent_grouped` and
  `rate_limits_repo.count_recent_totals`, assembles the response.

### 7. `backend/routers/admin.py`

```python
@router.get("/admin/traffic/hourly", response_model=TrafficHourlyRollupListOut, responses=_ADMIN_ONLY)
async def traffic_hourly_rollups(
    limit: int = Query(default=48, ge=1, le=168),
    current_user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TrafficHourlyRollupListOut:
    return await admin_service.list_hourly_traffic_rollups(session, limit)


@router.get("/admin/rate-limit-summary", response_model=RateLimitSummaryOut, responses=_ADMIN_ONLY)
async def rate_limit_summary(
    window_hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=25, ge=1, le=100),
    current_user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RateLimitSummaryOut:
    return await admin_service.get_rate_limit_summary(session, window_hours=window_hours, limit=limit)
```

Both admin/owner-only, same `_ADMIN_ONLY` responses dict already used by
every other endpoint in this router — no new auth pattern.

### 8. `backend/core/config.py`

```python
traffic_hourly_rollup_interval_seconds: int = 60 * 60
traffic_hourly_rollup_retention_days: int = 7
```

### 9. `backend/worker.py`

Add `run_hourly_traffic_rollup_forever()` as a fifth loop inside
`asyncio.gather(...)` in `run_all_forever()`, alongside the existing four
— same pattern, same file, same import style as the daily loop already
there.

### 10. `frontend/src/pages/admin/traffic.astro`

- Fetch `GET /api/v1/admin/traffic/hourly` alongside the existing daily
  fetch (same `createApiClient` instance, same cookie-forwarding pattern).
- New stat card in `.latest-summary`: bot-traffic share for the latest
  day, e.g. "62% known bots" derived from `latest.bot_breakdown`.
- New section "Last 24 hours" below the existing "Recent history" table:
  a compact table (hour, requests, known-bot count) sourced from the
  hourly fetch — same table styling already defined in this file, no new
  CSS system. An "empty" state identical in spirit to the existing daily
  one (hourly rollups may legitimately not exist yet on a fresh deploy of
  this feature).
- New section "Rate-limit activity" sourced from `GET /api/v1/admin/
  rate-limit-summary`: a one-line summary sentence (`total_events` /
  `distinct_identifiers` over `window_hours`) plus a flat table (scope,
  identifier, count, last seen) from `top_entries`, same table styling.
- "About this data" panel: add a fourth bullet-group (or extend "What's
  actually collected") disclosing the `userAgent`-derived classification
  and the hourly table's 7-day retention — both still Cloudflare-sourced
  aggregate data, not raw per-request logs, so the existing "why it's
  built this way" framing stays correct; this is an addition to it, not a
  rewrite. The rate-limit panel needs its own one-line note: sourced from
  `rate_limit_events`, which already existed for rate-limiting itself —
  not new data collection, just a new view onto it.

### 11. Docs

- `docs/decisions.md` — extend (not rewrite) the existing "Traffic
  dashboard shows real numbers..." entry with a dated addendum describing
  this expansion and why (the same append-only convention this file's own
  header states: "Entries are appended, not rewritten — a superseded
  decision is marked superseded rather than deleted").
- `docs/API.md` — add `GET /admin/traffic/hourly` and `GET /admin/
  rate-limit-summary` to the Authentication table's admin-endpoint row
  (which currently lists `/admin/users` and its two PATCH routes, but
  not even the existing `/admin/traffic` — fix that omission too while
  touching this line, since it's the same one-line edit).

## Testing

- `classify_bot()` — pure unit tests: each known-bot token classifies
  correctly (case-insensitive), a real browser UA classifies as `"other"`,
  `None`/empty classifies as `"other"`.
- `aggregate_rollup()` — extend existing tests with `userAgent` in sample
  group dimensions; assert `bot_breakdown` sums correctly and always
  contains both categories (even count-0 ones).
- Repository functions — real Postgres tests (this project's standing
  convention, never mocked): `upsert_hourly_rollup` + `list_hourly_rollups`
  round-trip; `prune_hourly_rollups_older_than` actually deletes rows
  older than cutoff and leaves newer ones; `list_recent_grouped` /
  `count_recent_totals` against seeded `rate_limit_events` rows, asserting
  correct grouping and that `count_recent_totals` isn't affected by the
  detail query's `LIMIT`.
- Router tests — `GET /admin/traffic/hourly` and `GET /admin/rate-limit-
  summary` both 401 unauthenticated, 403 non-admin, 200 with correct shape
  for admin/owner — same pattern as the existing `/admin/traffic` tests in
  `backend/tests/test_traffic_analytics.py`.
- Frontend — `astro check` / `astro build` clean; no Chromium available in
  this environment (standing constraint), so manual verification is via
  real HTTP + SSR HTML + compiled-bundle inspection, same as every prior
  frontend task in this project.

## Open questions / risks

- The 7-day hourly retention window and the known-bot token list are both
  easily-tunable constants, not load-bearing decisions — flagged here so a
  reviewer doesn't need to treat them as fixed.
- `meta-externalagent` alone accounted for the large majority of the
  investigated traffic. This design classifies and surfaces that; it does
  not rate-limit or block it — Cloudflare's own edge already fronts this
  zone, and blocking a legitimate link-preview crawler isn't in scope here
  without a separate, explicit decision (out of scope for this spec).
