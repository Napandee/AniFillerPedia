"""#221: daily Cloudflare traffic-analytics rollup + admin dashboard.

Mixed testing strategy, matching this project's own established
conventions:
- aggregate_rollup() is a pure function — plain unit tests, no DB/network.
- run_daily_traffic_rollup()'s Cloudflare HTTP boundary is mocked via
  httpx.MockTransport (the same pattern services/anilist_sync.py's own
  finished-series drift check is tested with — see
  test_finished_series_drift.py), never the real Cloudflare API — but
  persistence is asserted against REAL Postgres, never mocked, matching
  this project's standing DB-testing convention.
- The admin dashboard endpoint (GET /admin/traffic) is tested the same
  way test_admin.py already tests GET /admin/users: a real ASGI request
  through `main.app`, a real session cookie, real role-gating.
"""

import uuid
from datetime import date, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import services.traffic_analytics as traffic_analytics
from core.config import get_settings
from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from repositories.traffic_analytics import list_daily_rollups
from services.traffic_analytics import (
    _classify_path_kind,
    aggregate_rollup,
    run_daily_traffic_rollup,
)

TEST_PREFIX = "__test_221__"


@pytest.fixture(autouse=True)
def _clear_settings_cache_and_missing_token_flag(monkeypatch: pytest.MonkeyPatch):
    """get_settings() is @lru_cache'd (same gotcha test_config.py already
    documents) — clear it around every test in this file so env changes
    made here don't leak into/out of other test files. Also resets the
    module-level "already logged the missing-token warning once" flag,
    since that's deliberately global, cross-cycle state (see the module's
    own docstring on _logged_missing_token) that would otherwise make the
    no-token test order-dependent.
    """
    get_settings.cache_clear()
    monkeypatch.setattr(traffic_analytics, "_logged_missing_token", False)
    yield
    get_settings.cache_clear()


async def _cleanup_rollup(rollup_date: date) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM traffic_daily_rollups WHERE rollup_date = :d"), {"d": rollup_date}
            )


async def _create_user(role: str = "contributor") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO users (github_id, display_name, role) "
                    "VALUES (:gh, :name, :role) RETURNING id"
                ),
                {"gh": f"{TEST_PREFIX}{uuid.uuid4().hex[:12]}", "name": "Test User", "role": role},
            )
            return result.scalar_one()


async def _cleanup_user(user_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def _cookie(user_id: int) -> dict:
    return {SESSION_COOKIE_NAME: create_session_token(user_id)}


# --- _classify_path_kind / aggregate_rollup: pure unit tests ---------------


def test_classify_path_kind_api_prefix() -> None:
    assert _classify_path_kind("/api/v1/series") == "api"
    assert _classify_path_kind("/api/v1/health") == "api"


def test_classify_path_kind_frontend() -> None:
    assert _classify_path_kind("/") == "frontend"
    assert _classify_path_kind("/series/naruto") == "frontend"
    assert _classify_path_kind("/robots.txt") == "frontend"


def _group(path: str, method: str, status: int, country: str, count: int) -> dict:
    return {
        "count": count,
        "dimensions": {
            "clientRequestPath": path,
            "clientRequestHTTPMethodName": method,
            "edgeResponseStatus": status,
            "clientCountryName": country,
        },
    }


def test_aggregate_rollup_totals_and_splits_frontend_vs_api() -> None:
    groups = [
        _group("/", "GET", 200, "US", 49),
        _group("/api/v1/series", "GET", 200, "GB", 31),
        _group("/api/v1/license", "GET", 200, "GB", 18),
        _group("/series/null", "GET", 404, "US", 12),
    ]
    result = aggregate_rollup(groups)
    assert result["total_requests"] == 49 + 31 + 18 + 12

    by_path = {p["path"]: p for p in result["top_paths"]}
    assert by_path["/"]["path_kind"] == "frontend"
    assert by_path["/"]["count"] == 49
    assert by_path["/api/v1/series"]["path_kind"] == "api"
    assert by_path["/api/v1/series"]["count"] == 31
    # Real bug #220's own signature: a frontend 404.
    assert by_path["/series/null"]["path_kind"] == "frontend"


def test_aggregate_rollup_sums_same_path_across_method_status_country() -> None:
    """Cloudflare groups by the full (path, method, status, country)
    tuple — the same path legitimately appears in several input rows
    (e.g. served to two different countries). aggregate_rollup must
    collapse those back into one total per path, not report only the
    single highest-count tuple.
    """
    groups = [
        _group("/api/v1/series", "GET", 200, "US", 20),
        _group("/api/v1/series", "GET", 200, "GB", 15),
        _group("/api/v1/series", "POST", 201, "US", 1),
    ]
    result = aggregate_rollup(groups)
    assert result["total_requests"] == 36
    assert len(result["top_paths"]) == 1
    assert result["top_paths"][0]["path"] == "/api/v1/series"
    assert result["top_paths"][0]["count"] == 36


def test_aggregate_rollup_status_breakdown_and_top_countries() -> None:
    groups = [
        _group("/", "GET", 200, "US", 10),
        _group("/x", "GET", 200, "GB", 5),
        _group("/y", "GET", 404, "US", 3),
        _group("/z", "GET", 500, "FR", 1),
    ]
    result = aggregate_rollup(groups)
    statuses = {s["status"]: s["count"] for s in result["status_breakdown"]}
    assert statuses == {200: 15, 404: 3, 500: 1}
    countries = {c["country"]: c["count"] for c in result["top_countries"]}
    assert countries == {"US": 13, "GB": 5, "FR": 1}
    # Sorted descending by count.
    assert [s["status"] for s in result["status_breakdown"]] == [200, 404, 500]


def test_aggregate_rollup_truncates_to_top_n() -> None:
    groups = [_group(f"/p{i}", "GET", 200, "US", 100 - i) for i in range(20)]
    result = aggregate_rollup(groups, top_n_paths=5, top_n_countries=3)
    assert len(result["top_paths"]) == 5
    assert result["top_paths"][0]["path"] == "/p0"  # highest count kept
    # Only one country across all 20 groups, so top_countries has 1 entry
    # even though top_n_countries=3 — truncation is a cap, not a pad.
    assert len(result["top_countries"]) == 1


def test_aggregate_rollup_empty_groups() -> None:
    result = aggregate_rollup([])
    assert result == {
        "total_requests": 0,
        "top_paths": [],
        "status_breakdown": [],
        "top_countries": [],
    }


# --- run_daily_traffic_rollup: no-op-without-token + mocked-HTTP+real-DB --


@pytest.mark.asyncio
async def test_run_daily_traffic_rollup_noops_without_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("CLOUDFLARE_ANALYTICS_API_TOKEN", raising=False)
    get_settings.cache_clear()
    assert get_settings().cloudflare_analytics_api_token == ""

    with caplog.at_level("WARNING", logger="traffic_analytics"):
        persisted = await run_daily_traffic_rollup()

    assert persisted is False
    assert any(
        "CLOUDFLARE_ANALYTICS_API_TOKEN not set" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_daily_traffic_rollup_logs_missing_token_only_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("CLOUDFLARE_ANALYTICS_API_TOKEN", raising=False)
    get_settings.cache_clear()

    with caplog.at_level("WARNING", logger="traffic_analytics"):
        await run_daily_traffic_rollup()
        await run_daily_traffic_rollup()

    warnings = [r for r in caplog.records if "CLOUDFLARE_ANALYTICS_API_TOKEN not set" in r.message]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_run_daily_traffic_rollup_parses_and_persists_mocked_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_API_TOKEN", "test-token-not-real")
    get_settings.cache_clear()

    mocked_body = {
        "data": {
            "viewer": {
                "zones": [
                    {
                        "httpRequestsAdaptiveGroups": [
                            _group("/", "GET", 200, "US", 49),
                            _group("/api/v1/series", "GET", 200, "GB", 31),
                            _group("/api/v1/license", "GET", 200, "GB", 18),
                            _group("/series/null", "GET", 404, "US", 12),
                        ]
                    }
                ]
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token-not-real"
        return httpx.Response(200, json=mocked_body)

    real_async_client = httpx.AsyncClient

    def _fake_async_client(*args, **kwargs) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(traffic_analytics.httpx, "AsyncClient", _fake_async_client)

    today = date.today()
    try:
        persisted = await run_daily_traffic_rollup()
        assert persisted is True

        async with async_session_factory() as session:
            rows = await list_daily_rollups(session, limit=5)
        row = next(r for r in rows if r.rollup_date == today)
        assert row.total_requests == 49 + 31 + 18 + 12

        by_path = {p["path"]: p for p in row.top_paths}
        # Acceptance criterion: both a frontend path and an /api/v1/* path
        # captured in the same run.
        assert by_path["/"]["path_kind"] == "frontend"
        assert by_path["/api/v1/series"]["path_kind"] == "api"
        assert by_path["/api/v1/license"]["path_kind"] == "api"

        statuses = {s["status"] for s in row.status_breakdown}
        assert statuses == {200, 404}
    finally:
        await _cleanup_rollup(today)


@pytest.mark.asyncio
async def test_run_daily_traffic_rollup_upserts_same_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """A same-day rerun overwrites, not duplicates — the whole point of
    rollup_date being UNIQUE (migration 020)."""
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_API_TOKEN", "test-token-not-real")
    get_settings.cache_clear()

    def _handler_with_count(count: int):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "viewer": {
                            "zones": [
                                {
                                    "httpRequestsAdaptiveGroups": [
                                        _group("/", "GET", 200, "US", count)
                                    ]
                                }
                            ]
                        }
                    }
                },
            )

        return handler

    real_async_client = httpx.AsyncClient
    today = date.today()
    try:
        monkeypatch.setattr(
            traffic_analytics.httpx,
            "AsyncClient",
            lambda *a, **k: real_async_client(transport=httpx.MockTransport(_handler_with_count(10))),
        )
        await run_daily_traffic_rollup()

        monkeypatch.setattr(
            traffic_analytics.httpx,
            "AsyncClient",
            lambda *a, **k: real_async_client(transport=httpx.MockTransport(_handler_with_count(99))),
        )
        await run_daily_traffic_rollup()

        async with async_session_factory() as session:
            rows = await list_daily_rollups(session, limit=5)
        matching = [r for r in rows if r.rollup_date == today]
        assert len(matching) == 1
        assert matching[0].total_requests == 99
    finally:
        await _cleanup_rollup(today)


@pytest.mark.asyncio
async def test_run_daily_traffic_rollup_handles_http_failure_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_API_TOKEN", "test-token-not-real")
    get_settings.cache_clear()

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        traffic_analytics.httpx,
        "AsyncClient",
        lambda *a, **k: real_async_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(500))
        ),
    )

    persisted = await run_daily_traffic_rollup()
    assert persisted is False


# --- GET /admin/traffic: role-gating + real persisted-data rendering ------


@pytest.mark.asyncio
async def test_traffic_endpoint_requires_admin() -> None:
    contributor_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(contributor_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic")
        assert response.status_code == 403
    finally:
        await _cleanup_user(contributor_id)


@pytest.mark.asyncio
async def test_traffic_endpoint_unauthenticated_401() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/traffic")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_traffic_endpoint_returns_persisted_rollups() -> None:
    admin_id = await _create_user("admin")
    rollup_date = date.today() - timedelta(days=1)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                from repositories.traffic_analytics import upsert_daily_rollup

                await upsert_daily_rollup(
                    session,
                    rollup_date=rollup_date,
                    total_requests=42,
                    top_paths=[{"path": "/api/v1/series", "path_kind": "api", "count": 20}],
                    status_breakdown=[{"status": 200, "count": 42}],
                    top_countries=[{"country": "US", "count": 42}],
                )

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(admin_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic")
        assert response.status_code == 200
        body = response.json()
        row = next(r for r in body["items"] if r["rollup_date"] == rollup_date.isoformat())
        assert row["total_requests"] == 42
        assert row["top_paths"][0]["path_kind"] == "api"
        assert row["status_breakdown"][0]["status"] == 200
        assert row["top_countries"][0]["country"] == "US"
    finally:
        await _cleanup_rollup(rollup_date)
        await _cleanup_user(admin_id)


@pytest.mark.asyncio
async def test_traffic_endpoint_empty_state() -> None:
    """No rollups persisted at all (e.g. before the daily loop has ever
    run) is a legitimate 200 with an empty items list, not an error — the
    frontend renders its own "no data yet" message for this."""
    admin_id = await _create_user("owner")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text("DELETE FROM traffic_daily_rollups"))

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(admin_id)
        ) as client:
            response = await client.get("/api/v1/admin/traffic")
        assert response.status_code == 200
        assert response.json()["items"] == []
    finally:
        await _cleanup_user(admin_id)
