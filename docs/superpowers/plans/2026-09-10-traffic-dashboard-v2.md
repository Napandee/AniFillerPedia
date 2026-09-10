# Traffic Dashboard v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the admin traffic dashboard with bot/human traffic classification, hourly rollups, and an abuse-signal panel sourced from the app's own existing rate-limit bookkeeping — all from data already available, no new privacy-policy change, no Cloudflare plan upgrade.

**Architecture:** Extend the existing daily Cloudflare rollup pipeline (`services/traffic_analytics.py`) with a `userAgent`-derived bot classifier and a parallel hourly rollup cadence (its own table, 7-day retention). Add a second, independent vertical slice reading the already-existing `rate_limit_events` table for an abuse-signal panel. Both surface through extended/new `GET /admin/traffic*` endpoints into the existing `admin/traffic.astro` dashboard.

**Tech Stack:** FastAPI/SQLAlchemy Core/asyncpg/pytest (backend); Astro/TypeScript, plain DOM APIs, no framework (frontend) — matching this codebase throughout.

**Spec:** `docs/superpowers/specs/2026-09-10-traffic-dashboard-v2-design.md` — read it first; this plan argues from it. One deliberate refinement from the spec, decided while writing this plan: `bot_breakdown` follows the *exact same* "only categories that actually appeared" convention `status_breakdown`/`top_countries` already use (only emit an entry when its count > 0), rather than the spec's "always both categories" — simpler, and consistent with the rest of this file rather than inventing a second convention for one field. Concretely: `aggregate_rollup([])["bot_breakdown"] == []`, and a rollup with only bot traffic omits the `"other"` entry entirely (or vice versa).

## Global Constraints

- Every migration is additive only — no existing column altered/dropped (Guardrails).
- Every new/changed backend test runs against real Postgres — this project's standing convention, never mocked (`backend/tests/conftest.py`'s own docstring; `DATABASE_URL=postgresql+asyncpg://afp_test:testpass@127.0.0.1:55432/afp_test` for local runs, container `afp-test-pg`, currently stopped — `podman start afp-test-pg` before running any task's tests).
- `rate_limit_events` is wiped before every test in the suite by `backend/tests/conftest.py`'s autouse `_clear_rate_limit_events` fixture — new tests seed their own rows within the test, same as `backend/tests/test_rate_limits_and_validation.py`'s existing `_seed_rate_limit_events` helper. No special cleanup needed for that table.
- Cloudflare's HTTP boundary is mocked via `httpx.MockTransport` in tests — never a real call to Cloudflare's API (matches `test_traffic_analytics.py`'s existing convention exactly). Real-Cloudflare verification (confirming `userAgent`/`datetimeHour` dimensions actually work) was already done live against production during the design phase — not repeated per-task.
- `get_settings()` is `@lru_cache`'d — any test touching env-derived settings must `get_settings.cache_clear()` before and after, matching `test_traffic_analytics.py`'s existing `_clear_settings_cache_and_missing_token_flag` autouse fixture.
- Frontend: `astro check` and `astro build` must stay clean (no new type errors). No Chromium available in this environment — verify via SSR HTML / compiled-bundle inspection, same as every prior frontend task in this project.
- Every task's commit references issue `#251` (file this issue before Task 1 — see below) with `Fixes #251` only on the final task's commit; earlier tasks reference it without a closing keyword.

## Pre-flight: file the tracking issue

Before Task 1, file a GitHub issue for this work (per Guardrails — track before starting): title "Traffic dashboard v2: bot classification, hourly rollups, abuse-signal panel", body summarizing the spec's Motivation/Goals sections and linking `docs/superpowers/specs/2026-09-10-traffic-dashboard-v2-design.md`. Note its number (referred to as `#251` below — replace with the real number once filed) and add to the roadmap board per this repo's own `new-issue` skill convention.

---

## Task 1: Migration — `bot_breakdown` column + `traffic_hourly_rollups` table

**Files:**
- Create: `backend/migrations/022_add_traffic_bot_and_hourly_rollups.sql`
- Test: apply directly against `afp-test-pg` (no Python test for a migration file itself — this project has no migration-testing harness; verification is a direct `psql` check, same as every prior migration in this repo's history)

**Interfaces:**
- Produces: `traffic_daily_rollups.bot_breakdown` (JSONB NOT NULL DEFAULT `'[]'::jsonb`), `traffic_hourly_rollups` table (`id`, `rollup_hour` UNIQUE, `total_requests`, `top_paths`, `status_breakdown`, `top_countries`, `bot_breakdown`, `created_at`) — consumed by Task 3's repository functions.

- [ ] **Step 1: Write the migration file**

```sql
-- #251: bot/human traffic classification (userAgent-derived, see
-- services/traffic_analytics.py's classify_bot()) and hourly rollups
-- alongside the existing unlimited-history daily ones. Additive only.
--
-- bot_breakdown on traffic_daily_rollups: existing rows get '[]' via the
-- column default — the dashboard already treats an empty breakdown list
-- as "no data recorded," so pre-migration days simply show no bot split,
-- not an error.
--
-- traffic_hourly_rollups mirrors traffic_daily_rollups' shape exactly,
-- but serves a different purpose (recent-detail investigation, not
-- long-term trend) and so gets its own 7-day retention, pruned by
-- services/traffic_analytics.py's run_hourly_traffic_rollup() after each
-- cycle — not a set-and-forget table like its daily sibling.
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

- [ ] **Step 2: Apply to the local test-pg**

Run: `podman start afp-test-pg` (if not already running), then:
```bash
PGPASSWORD=testpass psql -h 127.0.0.1 -p 55432 -U afp_test -d afp_test \
  -f backend/migrations/022_add_traffic_bot_and_hourly_rollups.sql
```
Expected: `ALTER TABLE` / `CREATE TABLE` / `CREATE INDEX`, no errors.

- [ ] **Step 3: Verify**

```bash
PGPASSWORD=testpass psql -h 127.0.0.1 -p 55432 -U afp_test -d afp_test \
  -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='traffic_daily_rollups' AND column_name='bot_breakdown'; SELECT to_regclass('traffic_hourly_rollups');"
```
Expected: `bot_breakdown` then `traffic_hourly_rollups`, both non-empty.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/022_add_traffic_bot_and_hourly_rollups.sql
git commit -m "Add bot_breakdown column and traffic_hourly_rollups table (#251)"
```

---

## Task 2: `classify_bot()` + `aggregate_rollup()` bot-breakdown extension

**Files:**
- Modify: `backend/services/traffic_analytics.py`
- Test: `backend/tests/test_traffic_analytics.py`

**Interfaces:**
- Consumes: nothing new — pure function, no DB/network.
- Produces: `classify_bot(user_agent: str | None) -> str` (`"known_bot"` | `"other"`); `aggregate_rollup(...)`'s return dict gains `"bot_breakdown": list[dict]` — consumed by Task 3 (repository upsert) and Task 4 (both rollup runner functions).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_traffic_analytics.py`, near the existing `_classify_path_kind`/`aggregate_rollup` pure-unit-test section:

```python
from services.traffic_analytics import classify_bot  # add to the existing import block


def test_classify_bot_known_crawlers() -> None:
    assert classify_bot(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36 (compatible; meta-externalagent/1.1 "
        "(+https://developers.facebook.com/docs/sharing/webmasters/crawler))"
    ) == "known_bot"
    assert classify_bot(
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.7922.173 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ) == "known_bot"
    assert classify_bot("Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.4)") == "known_bot"


def test_classify_bot_is_case_insensitive() -> None:
    assert classify_bot("compatible; GOOGLEBOT/2.1") == "known_bot"


def test_classify_bot_real_browser_is_other() -> None:
    assert classify_bot(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ) == "other"


def test_classify_bot_missing_is_other() -> None:
    assert classify_bot(None) == "other"
    assert classify_bot("") == "other"


def _group_with_ua(path: str, status: int, country: str, user_agent: str, count: int) -> dict:
    return {
        "count": count,
        "dimensions": {
            "clientRequestPath": path,
            "clientRequestHTTPMethodName": "GET",
            "edgeResponseStatus": status,
            "clientCountryName": country,
            "userAgent": user_agent,
        },
    }


def test_aggregate_rollup_bot_breakdown_splits_and_sums() -> None:
    groups = [
        _group_with_ua("/login", 307, "US", "compatible; Googlebot/2.1", 10),
        _group_with_ua("/login", 200, "GB", "compatible; meta-externalagent/1.1", 5),
        _group_with_ua("/", 200, "US", "Mozilla/5.0 (Windows NT 10.0) Chrome/128.0.0.0", 3),
    ]
    result = aggregate_rollup(groups)
    bots = {b["category"]: b["count"] for b in result["bot_breakdown"]}
    assert bots == {"known_bot": 15, "other": 3}


def test_aggregate_rollup_bot_breakdown_omits_zero_categories() -> None:
    """Same convention as status_breakdown/top_countries: only categories
    that actually appeared are emitted, never a padded zero entry."""
    groups = [_group_with_ua("/", 200, "US", "compatible; Googlebot/2.1", 7)]
    result = aggregate_rollup(groups)
    assert result["bot_breakdown"] == [{"category": "known_bot", "count": 7}]


def test_aggregate_rollup_empty_groups_includes_bot_breakdown() -> None:
    result = aggregate_rollup([])
    assert result == {
        "total_requests": 0,
        "top_paths": [],
        "status_breakdown": [],
        "top_countries": [],
        "bot_breakdown": [],
    }
```

Also update the existing `test_aggregate_rollup_empty_groups` — delete it (superseded by
`test_aggregate_rollup_empty_groups_includes_bot_breakdown` above, which asserts the same
thing plus the new field) rather than leaving two overlapping tests.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -k "classify_bot or bot_breakdown" -v`
Expected: `classify_bot` tests fail with `ImportError`/`NameError` (function doesn't exist yet); `bot_breakdown` tests fail with `KeyError: 'bot_breakdown'`.

- [ ] **Step 3: Implement**

In `backend/services/traffic_analytics.py`, add after `_TOP_N_COUNTRIES`:

```python
# Case-insensitive substring match against a maintained set of known
# crawler/bot User-Agent tokens. Deliberately binary and honestly named:
# "known_bot" is a positive match against this list, "other" means
# "didn't match anything on this list" — never a claim that "other"
# traffic is confirmed human. Extend this tuple as new crawlers show up
# in real traffic (see docs/decisions.md's traffic-dashboard entry for
# the investigation that produced the initial list).
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

Add `userAgent` to `_QUERY`'s `dimensions` block (after `clientCountryName`):
```
          clientCountryName
          userAgent
```

In `aggregate_rollup()`, add a `bot_counts: dict[str, int] = {}` alongside the existing three count dicts, and inside the `for group in groups:` loop add:
```python
        category = classify_bot(dimensions.get("userAgent"))
        bot_counts[category] = bot_counts.get(category, 0) + count
```
Then, alongside the existing `top_paths`/`status_breakdown`/`top_countries` construction, add (same sorted-descending shape as `status_breakdown`, no top-N truncation — only two possible categories, no cap needed):
```python
    bot_breakdown = [
        {"category": category, "count": count}
        for category, count in sorted(bot_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
```
And add `"bot_breakdown": bot_breakdown,` to the function's returned dict, alongside the existing four keys.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -v`
Expected: all pass, including the pre-existing tests in this file (confirms the new `bot_breakdown` key doesn't break anything reading the other four keys).

- [ ] **Step 5: Commit**

```bash
git add backend/services/traffic_analytics.py backend/tests/test_traffic_analytics.py
git commit -m "Add classify_bot() and bot_breakdown to aggregate_rollup() (#251)"
```

---

## Task 3: Repository layer — extended daily upsert, hourly rollup CRUD, pruning

**Files:**
- Modify: `backend/repositories/traffic_analytics.py`, `backend/services/traffic_analytics.py` (Step 4's one-line caller fix)
- Test: `backend/tests/test_traffic_analytics.py`

**Interfaces:**
- Consumes: Task 1's `traffic_hourly_rollups` table; Task 2's `bot_breakdown` shape.
- Produces: `upsert_daily_rollup(..., bot_breakdown: list[dict])` (extended signature — this task also fixes its one real caller, `run_daily_traffic_rollup`, in the same commit, per Step 4 below); `upsert_hourly_rollup(session, *, rollup_hour: datetime, total_requests: int, top_paths: list[dict], status_breakdown: list[dict], top_countries: list[dict], bot_breakdown: list[dict]) -> None`; `list_hourly_rollups(session, limit: int = 48) -> list[Row]`; `prune_hourly_rollups_older_than(session, cutoff: datetime) -> None` — consumed by Task 4 and Task 6. Note: the API response (`TrafficRollupOut`) does not surface `bot_breakdown` until Task 6 — this task's own direct-`upsert_daily_rollup`-call test fix only needs to pass the new required arg, not assert on it via the HTTP response; Task 6's `test_traffic_endpoint_includes_bot_breakdown` owns that assertion.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_traffic_analytics.py`:

```python
from datetime import datetime, timezone  # add to existing datetime import line

from repositories.traffic_analytics import (  # extend existing import
    list_daily_rollups,
    list_hourly_rollups,
    prune_hourly_rollups_older_than,
    upsert_daily_rollup,
    upsert_hourly_rollup,
)


async def _cleanup_hourly_rollup(rollup_hour: datetime) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM traffic_hourly_rollups WHERE rollup_hour = :h"), {"h": rollup_hour}
            )


@pytest.mark.asyncio
async def test_upsert_daily_rollup_persists_bot_breakdown() -> None:
    rollup_date = date.today() - timedelta(days=2)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await upsert_daily_rollup(
                    session,
                    rollup_date=rollup_date,
                    total_requests=10,
                    top_paths=[{"path": "/", "path_kind": "frontend", "count": 10}],
                    status_breakdown=[{"status": 200, "count": 10}],
                    top_countries=[{"country": "US", "count": 10}],
                    bot_breakdown=[{"category": "known_bot", "count": 10}],
                )
        async with async_session_factory() as session:
            rows = await list_daily_rollups(session, limit=5)
        row = next(r for r in rows if r.rollup_date == rollup_date)
        assert row.bot_breakdown == [{"category": "known_bot", "count": 10}]
    finally:
        await _cleanup_rollup(rollup_date)


@pytest.mark.asyncio
async def test_upsert_and_list_hourly_rollups() -> None:
    rollup_hour = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await upsert_hourly_rollup(
                    session,
                    rollup_hour=rollup_hour,
                    total_requests=5,
                    top_paths=[{"path": "/api/v1/series", "path_kind": "api", "count": 5}],
                    status_breakdown=[{"status": 200, "count": 5}],
                    top_countries=[{"country": "GB", "count": 5}],
                    bot_breakdown=[{"category": "other", "count": 5}],
                )
        async with async_session_factory() as session:
            rows = await list_hourly_rollups(session, limit=10)
        row = next(r for r in rows if r.rollup_hour == rollup_hour)
        assert row.total_requests == 5
        assert row.bot_breakdown == [{"category": "other", "count": 5}]
    finally:
        await _cleanup_hourly_rollup(rollup_hour)


@pytest.mark.asyncio
async def test_upsert_hourly_rollup_same_hour_overwrites() -> None:
    rollup_hour = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await upsert_hourly_rollup(
                    session, rollup_hour=rollup_hour, total_requests=1,
                    top_paths=[], status_breakdown=[], top_countries=[], bot_breakdown=[],
                )
                await upsert_hourly_rollup(
                    session, rollup_hour=rollup_hour, total_requests=99,
                    top_paths=[], status_breakdown=[], top_countries=[], bot_breakdown=[],
                )
        async with async_session_factory() as session:
            rows = await list_hourly_rollups(session, limit=10)
        matching = [r for r in rows if r.rollup_hour == rollup_hour]
        assert len(matching) == 1
        assert matching[0].total_requests == 99
    finally:
        await _cleanup_hourly_rollup(rollup_hour)


@pytest.mark.asyncio
async def test_prune_hourly_rollups_older_than_cutoff() -> None:
    old_hour = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    recent_hour = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                for h in (old_hour, recent_hour):
                    await upsert_hourly_rollup(
                        session, rollup_hour=h, total_requests=1,
                        top_paths=[], status_breakdown=[], top_countries=[], bot_breakdown=[],
                    )
                await prune_hourly_rollups_older_than(
                    session, cutoff=datetime(2026, 9, 1, tzinfo=timezone.utc)
                )
        async with async_session_factory() as session:
            rows = await list_hourly_rollups(session, limit=100)
        hours = {r.rollup_hour for r in rows}
        assert old_hour not in hours
        assert recent_hour in hours
    finally:
        await _cleanup_hourly_rollup(recent_hour)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -k "hourly or bot_breakdown_persists" -v`
Expected: fail with `TypeError: upsert_daily_rollup() got an unexpected keyword argument 'bot_breakdown'` and `ImportError` for the three new hourly functions.

- [ ] **Step 3: Implement**

In `backend/repositories/traffic_analytics.py`, extend `upsert_daily_rollup`'s signature with `bot_breakdown: list[dict],` (after `top_countries`), add `bot_breakdown` to the `INSERT`/`ON CONFLICT DO UPDATE` column lists and the params dict (`"bot_breakdown": json.dumps(bot_breakdown)`), and add `bot_breakdown` to `list_daily_rollups`'s `SELECT` column list.

Add three new functions at the end of the file:

```python
async def upsert_hourly_rollup(
    session: AsyncSession,
    *,
    rollup_hour,
    total_requests: int,
    top_paths: list[dict],
    status_breakdown: list[dict],
    top_countries: list[dict],
    bot_breakdown: list[dict],
) -> None:
    """Same idempotent-upsert shape as upsert_daily_rollup above, keyed by
    rollup_hour instead of rollup_date."""
    await session.execute(
        text(
            """
            INSERT INTO traffic_hourly_rollups
                (rollup_hour, total_requests, top_paths, status_breakdown, top_countries, bot_breakdown)
            VALUES
                (:rollup_hour, :total_requests, CAST(:top_paths AS JSONB),
                 CAST(:status_breakdown AS JSONB), CAST(:top_countries AS JSONB),
                 CAST(:bot_breakdown AS JSONB))
            ON CONFLICT (rollup_hour) DO UPDATE SET
                total_requests   = EXCLUDED.total_requests,
                top_paths        = EXCLUDED.top_paths,
                status_breakdown = EXCLUDED.status_breakdown,
                top_countries    = EXCLUDED.top_countries,
                bot_breakdown    = EXCLUDED.bot_breakdown
            """
        ),
        {
            "rollup_hour": rollup_hour,
            "total_requests": total_requests,
            "top_paths": json.dumps(top_paths),
            "status_breakdown": json.dumps(status_breakdown),
            "top_countries": json.dumps(top_countries),
            "bot_breakdown": json.dumps(bot_breakdown),
        },
    )


async def list_hourly_rollups(session: AsyncSession, limit: int = 48) -> list[Row]:
    """Most recent `limit` hours, newest first — default 48 (two days)
    comfortably inside the 7-day retention window pruning enforces."""
    result = await session.execute(
        text(
            """
            SELECT id, rollup_hour, total_requests, top_paths, status_breakdown,
                   top_countries, bot_breakdown, created_at
            FROM traffic_hourly_rollups
            ORDER BY rollup_hour DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return list(result.fetchall())


async def prune_hourly_rollups_older_than(session: AsyncSession, cutoff) -> None:
    """Deletes every hourly row older than `cutoff` — called once per
    cycle by run_hourly_traffic_rollup() after a successful persist, so
    this table never grows past its 7-day retention window."""
    await session.execute(
        text("DELETE FROM traffic_hourly_rollups WHERE rollup_hour < :cutoff"),
        {"cutoff": cutoff},
    )
```

- [ ] **Step 4: Fix the one broken production call site**

This task's `upsert_daily_rollup` signature change (new required `bot_breakdown` param)
breaks its one existing production caller. Fix it in the same task that broke it, so this
task leaves the suite fully green rather than handing a known failure to the next task.

In `backend/services/traffic_analytics.py`'s `run_daily_traffic_rollup()`, change:
```python
            await upsert_daily_rollup(
                session,
                rollup_date=until.date(),
                total_requests=rollup["total_requests"],
                top_paths=rollup["top_paths"],
                status_breakdown=rollup["status_breakdown"],
                top_countries=rollup["top_countries"],
            )
```
to add `bot_breakdown=rollup["bot_breakdown"],` after `top_countries=rollup["top_countries"],`.
(`rollup["bot_breakdown"]` already exists — Task 2 added it to `aggregate_rollup()`'s return.)

Also fix `test_traffic_endpoint_returns_persisted_rollups` in
`backend/tests/test_traffic_analytics.py` — its own direct `upsert_daily_rollup(...)` call
breaks the same way. Add `bot_breakdown=[{"category": "known_bot", "count": 42}],` to that
call only. Do **not** add an assertion on `row["bot_breakdown"]` in this test — the
`GET /admin/traffic` response schema (`TrafficRollupOut`) doesn't surface that field until
Task 6, so asserting on it here would fail for a reason outside this task's scope. Task 6's
`test_traffic_endpoint_includes_bot_breakdown` already owns that HTTP-response-level
assertion once the schema exposes it — this task only needs the repository call itself to
compile and run.

- [ ] **Step 5: Run to verify everything passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -v`
Expected: all pass — the whole file, including every pre-existing test, with no known
failures left over for the next task.

- [ ] **Step 6: Commit**

```bash
git add backend/repositories/traffic_analytics.py backend/services/traffic_analytics.py backend/tests/test_traffic_analytics.py
git commit -m "Extend upsert_daily_rollup for bot_breakdown; add hourly rollup repository functions (#251)"
```

---

## Task 4: Wire up hourly rollup runner, config, and worker loop

**Files:**
- Modify: `backend/services/traffic_analytics.py`, `backend/core/config.py`, `backend/worker.py`
- Test: `backend/tests/test_traffic_analytics.py`

**Interfaces:**
- Consumes: Task 2's `aggregate_rollup()` (now returns `bot_breakdown`); Task 3's `upsert_hourly_rollup`/`prune_hourly_rollups_older_than`.
- Produces: `run_hourly_traffic_rollup() -> bool`, `run_hourly_traffic_rollup_forever() -> None`; `settings.traffic_hourly_rollup_interval_seconds`, `settings.traffic_hourly_rollup_retention_days` — consumed by `worker.py`'s `run_all_forever()`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_traffic_analytics.py` (mirrors the existing `test_run_daily_traffic_rollup_*` tests exactly, adapted for the hourly function):

```python
from services.traffic_analytics import (  # extend existing import
    run_hourly_traffic_rollup,
)


@pytest.mark.asyncio
async def test_run_hourly_traffic_rollup_noops_without_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("CLOUDFLARE_ANALYTICS_API_TOKEN", raising=False)
    get_settings.cache_clear()
    with caplog.at_level("WARNING", logger="traffic_analytics"):
        persisted = await run_hourly_traffic_rollup()
    assert persisted is False


@pytest.mark.asyncio
async def test_run_hourly_traffic_rollup_persists_and_prunes_old_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_API_TOKEN", "test-token-not-real")
    get_settings.cache_clear()

    mocked_body = {
        "data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
            _group_with_ua("/login", 307, "US", "compatible; Googlebot/2.1", 7),
        ]}]}}
    }
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        traffic_analytics.httpx, "AsyncClient",
        lambda *a, **k: real_async_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=mocked_body))
        ),
    )

    # A stale row this cycle's prune step must remove.
    old_hour = datetime(2000, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        async with session.begin():
            await upsert_hourly_rollup(
                session, rollup_hour=old_hour, total_requests=1,
                top_paths=[], status_breakdown=[], top_countries=[], bot_breakdown=[],
            )

    persisted = await run_hourly_traffic_rollup()
    assert persisted is True

    async with async_session_factory() as session:
        rows = await list_hourly_rollups(session, limit=100)
    assert not any(r.rollup_hour == old_hour for r in rows), "stale row should have been pruned"
    latest = max(rows, key=lambda r: r.rollup_hour)
    assert latest.total_requests == 7
    assert latest.bot_breakdown == [{"category": "known_bot", "count": 7}]
    await _cleanup_hourly_rollup(latest.rollup_hour)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -k hourly_traffic_rollup -v`
Expected: `ImportError: cannot import name 'run_hourly_traffic_rollup'`.

- [ ] **Step 3: Implement**

`backend/core/config.py` — add near `traffic_rollup_interval_seconds`:
```python
    traffic_hourly_rollup_interval_seconds: int = 60 * 60
    traffic_hourly_rollup_retention_days: int = 7
```

`backend/services/traffic_analytics.py` — add (Task 3 already fixed `run_daily_traffic_
rollup()`'s call site, so this task only adds new code, nothing to reconcile there):

```python
_logged_missing_hourly_token = False


async def run_hourly_traffic_rollup() -> bool:
    """Same shape as run_daily_traffic_rollup, but a 1h window and its
    own retention pruning — see this file's module docstring / the design
    spec for why hourly gets a short retention while daily doesn't.
    """
    global _logged_missing_hourly_token
    settings = get_settings()

    if not settings.cloudflare_analytics_api_token:
        if not _logged_missing_hourly_token:
            logger.warning(
                "CLOUDFLARE_ANALYTICS_API_TOKEN not set — hourly traffic rollup skipped "
                "(structurally ready, not live-configured yet; this message logs once)"
            )
            _logged_missing_hourly_token = True
        return False

    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=1)

    groups = await _fetch_traffic_groups(
        token=settings.cloudflare_analytics_api_token,
        zone_id=settings.cloudflare_zone_id,
        since=since,
        until=until,
    )
    if groups is None:
        return False

    rollup = aggregate_rollup(groups)
    rollup_hour = until.replace(minute=0, second=0, microsecond=0)
    cutoff = until - timedelta(days=settings.traffic_hourly_rollup_retention_days)

    async with async_session_factory() as session:
        async with session.begin():
            await upsert_hourly_rollup(
                session,
                rollup_hour=rollup_hour,
                total_requests=rollup["total_requests"],
                top_paths=rollup["top_paths"],
                status_breakdown=rollup["status_breakdown"],
                top_countries=rollup["top_countries"],
                bot_breakdown=rollup["bot_breakdown"],
            )
            await prune_hourly_rollups_older_than(session, cutoff=cutoff)
    return True


async def run_hourly_traffic_rollup_forever() -> None:
    settings = get_settings()
    logger.info(
        "hourly traffic rollup starting: interval=%ss",
        settings.traffic_hourly_rollup_interval_seconds,
    )
    while True:
        try:
            persisted = await run_hourly_traffic_rollup()
            if persisted:
                logger.info("persisted hourly traffic rollup")
        except Exception:
            logger.exception("error during hourly traffic rollup cycle — continuing")
        await asyncio.sleep(settings.traffic_hourly_rollup_interval_seconds)
```

Add the two new repository imports (`upsert_hourly_rollup`, `prune_hourly_rollups_older_than`)
to this file's existing `from repositories.traffic_analytics import ...` line.

`backend/worker.py` — add `run_hourly_traffic_rollup_forever` to the existing
`from services.traffic_analytics import run_traffic_rollup_forever` line, and add
`run_hourly_traffic_rollup_forever(),` as a fifth entry in `run_all_forever()`'s
`asyncio.gather(...)` call, updating that function's own comment
(`# #221: a fourth loop...`) to say "a fourth and fifth loop" and mention #251.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -v`
Expected: all pass, including every pre-existing test in this file.

- [ ] **Step 5: Commit**

```bash
git add backend/services/traffic_analytics.py backend/core/config.py backend/worker.py backend/tests/test_traffic_analytics.py
git commit -m "Add hourly traffic rollup loop with 7-day retention pruning (#251)"
```

---

## Task 5: Abuse-signal vertical slice — rate-limit summary repository, service, router

**Files:**
- Modify: `backend/repositories/rate_limits.py`, `backend/schemas/admin.py`, `backend/services/admin.py`, `backend/routers/admin.py`
- Test: `backend/tests/test_rate_limits_and_validation.py` (repository-level), `backend/tests/test_admin.py` (router-level)

**Interfaces:**
- Consumes: existing `rate_limit_events` table (no schema change).
- Produces: `list_recent_grouped(session, *, window_hours: int, limit: int) -> list[Row]`; `count_recent_totals(session, *, window_hours: int) -> Row`; `RateLimitEventSummaryEntryOut`, `RateLimitSummaryOut` schemas; `get_rate_limit_summary(session, *, window_hours: int, limit: int) -> RateLimitSummaryOut`; `GET /admin/rate-limit-summary` — consumed by Task 7 (frontend).

- [ ] **Step 1: Write the failing repository tests**

Add to `backend/tests/test_rate_limits_and_validation.py` (this file already has
`_seed_rate_limit_events` and the autouse clearing fixture — reuse both):

```python
from repositories.rate_limits import count_recent_totals, list_recent_grouped  # new import


@pytest.mark.asyncio
async def test_list_recent_grouped_counts_per_scope_and_identifier() -> None:
    await _seed_rate_limit_events("local_login", "login:a@example.com:ip:1.2.3.4", 3)
    await _seed_rate_limit_events("local_login", "login:b@example.com:ip:5.6.7.8", 1)
    await _seed_rate_limit_events("anilist_lookup", "ip:1.2.3.4", 2)

    async with async_session_factory() as session:
        rows = await list_recent_grouped(session, window_hours=24, limit=10)

    by_identifier = {(r.scope, r.identifier): r.event_count for r in rows}
    assert by_identifier[("local_login", "login:a@example.com:ip:1.2.3.4")] == 3
    assert by_identifier[("local_login", "login:b@example.com:ip:5.6.7.8")] == 1
    assert by_identifier[("anilist_lookup", "ip:1.2.3.4")] == 2
    # Sorted descending by count.
    assert rows[0].event_count >= rows[-1].event_count


@pytest.mark.asyncio
async def test_list_recent_grouped_respects_limit() -> None:
    for i in range(5):
        await _seed_rate_limit_events("local_login", f"login:user{i}@example.com:ip:1.2.3.4", 1)

    async with async_session_factory() as session:
        rows = await list_recent_grouped(session, window_hours=24, limit=2)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_count_recent_totals_unaffected_by_detail_limit() -> None:
    for i in range(5):
        await _seed_rate_limit_events("local_login", f"login:user{i}@example.com:ip:1.2.3.4", 2)

    async with async_session_factory() as session:
        totals = await count_recent_totals(session, window_hours=24)
    assert totals.total_events == 10
    assert totals.distinct_identifiers == 5
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rate_limits_and_validation.py -k "recent_grouped or count_recent_totals" -v`
Expected: `ImportError` — neither function exists yet.

- [ ] **Step 3: Implement the repository functions**

In `backend/repositories/rate_limits.py`, add:

```python
async def list_recent_grouped(
    session: AsyncSession, *, window_hours: int, limit: int
) -> list:
    """Per (scope, identifier) counts within the window, most-active
    first — the abuse-signal dashboard panel's data source."""
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


async def count_recent_totals(session: AsyncSession, *, window_hours: int):
    """Headline totals for the same window, independent of list_recent_
    grouped's LIMIT — so a summary sentence stays accurate even when the
    detail table is truncated."""
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

- [ ] **Step 4: Run to verify the repository tests pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rate_limits_and_validation.py -v`
Expected: all pass, including the whole pre-existing file (nothing else touched).

- [ ] **Step 5: Write the failing router test**

Add to `backend/tests/test_admin.py`. This file's own existing helpers (confirmed by
reading it): `_create_user(role: str = "contributor") -> int`, `_cookie(user_id: int) ->
dict`, and cleanup via `_cleanup(*user_ids: int) -> None` (note: this file's cleanup helper
takes variadic user ids, unlike `test_traffic_analytics.py`'s single-argument
`_cleanup_user` — use `_cleanup(...)` here, matching this file specifically):

```python
@pytest.mark.asyncio
async def test_rate_limit_summary_requires_admin() -> None:
    contributor_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(contributor_id)
        ) as client:
            response = await client.get("/api/v1/admin/rate-limit-summary")
        assert response.status_code == 403
    finally:
        await _cleanup(contributor_id)


@pytest.mark.asyncio
async def test_rate_limit_summary_returns_grouped_data() -> None:
    admin_id = await _create_user("admin")
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("INSERT INTO rate_limit_events (scope, identifier) VALUES "
                     "('local_login', '__test_251__ip:9.9.9.9'), "
                     "('local_login', '__test_251__ip:9.9.9.9')")
            )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(admin_id)
        ) as client:
            response = await client.get("/api/v1/admin/rate-limit-summary")
        assert response.status_code == 200
        body = response.json()
        assert body["window_hours"] == 24
        entry = next(e for e in body["top_entries"] if e["identifier"] == "__test_251__ip:9.9.9.9")
        assert entry["count"] == 2
        assert entry["scope"] == "local_login"
    finally:
        await _cleanup(admin_id)
```

(`rate_limit_events` is cleared by the suite-wide autouse fixture before this test runs, and
this test seeds only its own rows — no explicit cleanup of those rows needed, matching this
suite's existing convention for that table.)

- [ ] **Step 6: Run to verify the router test fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_admin.py -k rate_limit_summary -v`
Expected: 404 (route doesn't exist yet).

- [ ] **Step 7: Implement schemas, service, router**

`backend/schemas/admin.py` — add:
```python
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

`backend/services/admin.py` — add (import `repositories.rate_limits as rate_limits_repo` at
the top of the file if not already imported):
```python
async def get_rate_limit_summary(session, *, window_hours: int, limit: int) -> RateLimitSummaryOut:
    """#251: the abuse-signal dashboard panel's data source — reads the
    same rate_limit_events table every rate-limited endpoint already
    writes to, not a new collection mechanism."""
    rows = await rate_limits_repo.list_recent_grouped(session, window_hours=window_hours, limit=limit)
    totals = await rate_limits_repo.count_recent_totals(session, window_hours=window_hours)
    return RateLimitSummaryOut(
        window_hours=window_hours,
        total_events=totals.total_events,
        distinct_identifiers=totals.distinct_identifiers,
        top_entries=[
            RateLimitEventSummaryEntryOut(
                scope=row.scope,
                identifier=row.identifier,
                count=row.event_count,
                first_seen=row.first_seen.isoformat(),
                last_seen=row.last_seen.isoformat(),
            )
            for row in rows
        ],
    )
```

`backend/routers/admin.py` — add `RateLimitSummaryOut` to the existing `from schemas.admin
import (...)` block, then:
```python
@router.get("/admin/rate-limit-summary", response_model=RateLimitSummaryOut, responses=_ADMIN_ONLY)
async def rate_limit_summary(
    window_hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=25, ge=1, le=100),
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> RateLimitSummaryOut:
    """#251: per-(scope, identifier) rate-limit activity over the last
    `window_hours` — the app's own already-collected rate-limit
    bookkeeping (repositories/rate_limits.py), not a new data source.
    """
    return await admin_service.get_rate_limit_summary(session, window_hours=window_hours, limit=limit)
```

- [ ] **Step 8: Run to verify everything passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_admin.py tests/test_rate_limits_and_validation.py -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/repositories/rate_limits.py backend/schemas/admin.py backend/services/admin.py backend/routers/admin.py backend/tests/test_rate_limits_and_validation.py backend/tests/test_admin.py
git commit -m "Add GET /admin/rate-limit-summary abuse-signal endpoint (#251)"
```

---

## Task 6: Traffic hourly API surface — schemas, service, router

**Files:**
- Modify: `backend/schemas/admin.py`, `backend/services/admin.py`, `backend/routers/admin.py`
- Test: `backend/tests/test_traffic_analytics.py`

**Interfaces:**
- Consumes: Task 3's `list_hourly_rollups`; Task 2's `bot_breakdown` shape.
- Produces: `TrafficBotEntryOut`, extended `TrafficRollupOut` (gains `bot_breakdown`), `TrafficHourlyRollupOut`, `TrafficHourlyRollupListOut`; `list_hourly_traffic_rollups(session, limit) -> TrafficHourlyRollupListOut`; `GET /admin/traffic/hourly` — consumed by Task 7 (frontend).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_traffic_analytics.py`:

```python
@pytest.mark.asyncio
async def test_traffic_endpoint_includes_bot_breakdown() -> None:
    admin_id = await _create_user("admin")
    rollup_date = date.today() - timedelta(days=3)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await upsert_daily_rollup(
                    session, rollup_date=rollup_date, total_requests=5,
                    top_paths=[{"path": "/", "path_kind": "frontend", "count": 5}],
                    status_breakdown=[{"status": 200, "count": 5}],
                    top_countries=[{"country": "US", "count": 5}],
                    bot_breakdown=[{"category": "known_bot", "count": 5}],
                )
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(admin_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic")
        body = response.json()
        row = next(r for r in body["items"] if r["rollup_date"] == rollup_date.isoformat())
        assert row["bot_breakdown"] == [{"category": "known_bot", "count": 5}]
    finally:
        await _cleanup_rollup(rollup_date)
        await _cleanup_user(admin_id)


@pytest.mark.asyncio
async def test_hourly_traffic_endpoint_requires_admin() -> None:
    contributor_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(contributor_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic/hourly")
        assert response.status_code == 403
    finally:
        await _cleanup_user(contributor_id)


@pytest.mark.asyncio
async def test_hourly_traffic_endpoint_returns_persisted_rollups() -> None:
    admin_id = await _create_user("admin")
    rollup_hour = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await upsert_hourly_rollup(
                    session, rollup_hour=rollup_hour, total_requests=3,
                    top_paths=[{"path": "/", "path_kind": "frontend", "count": 3}],
                    status_breakdown=[{"status": 200, "count": 3}],
                    top_countries=[{"country": "US", "count": 3}],
                    bot_breakdown=[{"category": "other", "count": 3}],
                )
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(admin_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic/hourly")
        assert response.status_code == 200
        body = response.json()
        row = next(r for r in body["items"] if r["rollup_hour"] == rollup_hour.isoformat())
        assert row["total_requests"] == 3
        assert row["bot_breakdown"] == [{"category": "other", "count": 3}]
    finally:
        await _cleanup_hourly_rollup(rollup_hour)
        await _cleanup_user(admin_id)


@pytest.mark.asyncio
async def test_hourly_traffic_endpoint_empty_state() -> None:
    admin_id = await _create_user("owner")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text("DELETE FROM traffic_hourly_rollups"))
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(admin_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic/hourly")
        assert response.status_code == 200
        assert response.json()["items"] == []
    finally:
        await _cleanup_user(admin_id)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -k "bot_breakdown or hourly_traffic_endpoint" -v`
Expected: `test_traffic_endpoint_includes_bot_breakdown` fails on a missing `bot_breakdown` key
in the response (schema doesn't expose it yet); the two hourly-endpoint tests 404.

- [ ] **Step 3: Implement**

`backend/schemas/admin.py`:
```python
class TrafficBotEntryOut(BaseModel):
    category: str = Field(description="'known_bot' or 'other' — a heuristic User-Agent classification, not a certainty claim")
    count: int
```
Add `bot_breakdown: list[TrafficBotEntryOut]` to the existing `TrafficRollupOut`. Add:
```python
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
```

`backend/services/admin.py` — add `bot_breakdown=[TrafficBotEntryOut(**e) for e in row.bot_breakdown],`
to the existing `list_traffic_rollups`'s `TrafficRollupOut(...)` construction, and add:
```python
async def list_hourly_traffic_rollups(session, limit: int) -> TrafficHourlyRollupListOut:
    """#251: the hourly counterpart to list_traffic_rollups above — same
    mapping shape, 7-day-retention table instead of unlimited-history."""
    rows = await traffic_repo.list_hourly_rollups(session, limit)
    items = [
        TrafficHourlyRollupOut(
            rollup_hour=row.rollup_hour.isoformat(),
            total_requests=row.total_requests,
            top_paths=[TrafficPathEntryOut(**entry) for entry in row.top_paths],
            status_breakdown=[TrafficStatusEntryOut(**entry) for entry in row.status_breakdown],
            top_countries=[TrafficCountryEntryOut(**entry) for entry in row.top_countries],
            bot_breakdown=[TrafficBotEntryOut(**entry) for entry in row.bot_breakdown],
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return TrafficHourlyRollupListOut(items=items)
```
(Import `TrafficBotEntryOut`, `TrafficHourlyRollupOut`, `TrafficHourlyRollupListOut` alongside
this file's existing traffic-schema imports.)

`backend/routers/admin.py` — add the same three schema names to the existing import block,
then:
```python
@router.get("/admin/traffic/hourly", response_model=TrafficHourlyRollupListOut, responses=_ADMIN_ONLY)
async def traffic_hourly_rollups(
    limit: int = Query(default=48, ge=1, le=168),
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> TrafficHourlyRollupListOut:
    """#251: hourly counterpart to GET /admin/traffic — 7-day retention,
    for recent-spike investigation rather than long-term trend."""
    return await admin_service.list_hourly_traffic_rollups(session, limit)
```

- [ ] **Step 4: Run to verify everything passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_traffic_analytics.py -v`
Expected: all pass — the full file, not just the new tests.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: same pass/fail count as this project's known baseline (5 AniList-outage failures if
that's still ongoing — check live before assuming; zero *new* failures beyond that).

- [ ] **Step 6: Commit**

```bash
git add backend/schemas/admin.py backend/services/admin.py backend/routers/admin.py backend/tests/test_traffic_analytics.py
git commit -m "Add GET /admin/traffic/hourly and expose bot_breakdown on GET /admin/traffic (#251)"
```

---

## Task 7: Frontend — bot split, hourly section, abuse panel

**Files:**
- Modify: `frontend/src/pages/admin/traffic.astro`
- Regenerate: `frontend/src/api/schema.d.ts`, `frontend/src/api/openapi.json` (typed client codegen against the now-extended backend OpenAPI schema)

**Interfaces:**
- Consumes: `GET /api/v1/admin/traffic` (now includes `bot_breakdown`), `GET /api/v1/admin/traffic/hourly`, `GET /api/v1/admin/rate-limit-summary` (all from Tasks 5–6).

- [ ] **Step 1: Regenerate the typed API client**

With the backend running locally (`uvicorn` on `:8000` with Tasks 1–6's changes applied —
`cd backend && .venv/bin/uvicorn main:app --port 8000`, `DATABASE_URL` pointed at
`afp-test-pg` per this plan's Global Constraints), run:
```bash
cd frontend && npm run generate:api-client
```
This fetches `http://localhost:8000/openapi.json` and regenerates `src/api/schema.d.ts` (see
`frontend/scripts/fetch-schema.mjs` for exactly what it does) so `TrafficRollupOut`/
`TrafficHourlyRollupOut`/`RateLimitSummaryOut` are typed client-side.

- [ ] **Step 2: Fetch the two new endpoints**

In `traffic.astro`'s frontmatter, alongside the existing `api.GET("/api/v1/admin/traffic", ...)`
call, add:
```typescript
const { data: hourlyData } = await api.GET("/api/v1/admin/traffic/hourly", {
  params: { query: { limit: 48 } },
  headers: { cookie },
});
const hourlyRollups = hourlyData?.items ?? [];

const { data: rateLimitData } = await api.GET("/api/v1/admin/rate-limit-summary", {
  params: { query: { window_hours: 24, limit: 25 } },
  headers: { cookie },
});
```
(No `error` destructured for these two — matching this page's existing tolerant style for
non-critical sections: an empty/missing result renders an empty-state, not a page-level error,
same as the existing `hasData`/`latest` handling.)

- [ ] **Step 3: Add the bot-share stat card**

In `.latest-summary`, add a fourth `.stat-card` computing a bot-traffic percentage from
`latest.bot_breakdown` (find the `known_bot` entry, divide by `latest.total_requests`,
`0%` if `bot_breakdown` is empty) — same `stat-card`/`stat-label`/`stat-value` markup as the
three existing cards, no new CSS class needed.

- [ ] **Step 4: Add the "Last 24 hours" hourly section**

Below the existing "Recent history" `.history-block`, add a new `.table-block` titled
"Last 24 hours" rendering `hourlyRollups` (hour formatted via a new small helper alongside
the existing `formatDate`, e.g. `formatHour(iso)` using `toLocaleTimeString` with
`{hour: "2-digit", timeZone: "UTC"}`) — columns: Hour, Requests, Known bots. Empty state
("No hourly data yet") matching the existing empty-state tone when `hourlyRollups.length === 0`.

- [ ] **Step 5: Add the "Rate-limit activity" panel**

New section after the hourly one: one summary sentence
(`` `${total_events} events across ${distinct_identifiers} identifiers in the last ${window_hours}h` ``)
plus a table (Scope, Identifier, Count, Last seen) from `rateLimitData?.top_entries ?? []`,
same table styling as every other table on this page. Empty state: "No rate-limit activity in
this window" when `top_entries` is empty.

- [ ] **Step 6: Update "About this data"**

Extend (don't rewrite) the existing "What's actually collected" paragraph to mention the
`userAgent`-derived bot/human split is now part of the Cloudflare-sourced daily/hourly
aggregate (still no per-visitor data — the classification happens on Cloudflare's own
aggregate group data, same as everything else on this page). Add one line noting hourly
rollups keep only 7 days of history, unlike the daily table's unlimited retention. Add one
line noting the rate-limit panel is sourced from data that already existed for rate-limiting
itself, not a new collection mechanism.

- [ ] **Step 7: Verify**

Run: `cd frontend && npm run build` (or this project's equivalent `astro check` + `astro build`
command — check `package.json`). Expected: clean, zero new errors/warnings beyond the one
known pre-existing hint on `admin/index.astro` (unrelated to this page).

Manually inspect the compiled SSR output (no Chromium available) to confirm the new sections
render with real or empty-state content as expected, same verification method as every prior
frontend task in this project.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/admin/traffic.astro frontend/src/api/schema.d.ts frontend/src/api/openapi.json
git commit -m "Add bot-split stat, hourly section, and rate-limit panel to the traffic dashboard (#251)"
```

---

## Task 8: Documentation

**Files:**
- Modify: `docs/decisions.md`, `docs/API.md`

**Interfaces:**
- Consumes: nothing new — this task only documents Tasks 1–7's finished shape.

- [ ] **Step 1: Extend `docs/decisions.md`**

Append to the existing "Traffic dashboard shows real numbers..." entry (append, don't rewrite
— per this file's own header convention) a dated addendum: bot/human classification via a
maintained `userAgent` token list (not Cloudflare Bot Management — confirmed unavailable on
this zone's plan, verified live), hourly rollups with 7-day retention, and the rate-limit-
summary panel sourced from already-existing `rate_limit_events` data. Note the concrete
investigation that prompted it (the login-traffic question, resolved as crawler noise, not
credential stuffing).

- [ ] **Step 2: Update `docs/API.md`**

Add `GET /admin/traffic`, `GET /admin/traffic/hourly`, and `GET /admin/rate-limit-summary` to
the Authentication section's admin-endpoint row (currently lists only `/admin/users` and its
two `PATCH` routes — `/admin/traffic` was already missing from this list before this plan;
fold that pre-existing gap fix in here since it's the same one-line edit).

- [ ] **Step 3: Commit**

```bash
git add docs/decisions.md docs/API.md
git commit -m "Document traffic dashboard v2: bot classification, hourly rollups, abuse panel (Fixes #251)"
```

---

## Final Review

Once all 8 tasks are complete: dispatch a whole-branch code reviewer (most capable available
model) covering the full diff against `master`, then use `superpowers:finishing-a-development-
branch` to merge/PR. Expect the same known-AniList-outage `build`-check failure pattern this
project has hit repeatedly if #237 is still open at merge time — verify live before assuming
it applies, same as every prior merge in this project's history.
