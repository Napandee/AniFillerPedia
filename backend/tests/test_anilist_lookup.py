"""Real-Postgres, real-network tests for #165 (live AniList ID lookup +
early duplicate detection on the series-proposal form) — same "hit the
real, public, unauthenticated AniList GraphQL API rather than mocking it"
convention as tests/test_anilist_sync.py.

Uses two real, stable AniList ids:
- 1735 (Naruto: Shippuuden) — confirmed already catalogued in this
  project's own test-pg snapshot (series.anilist_id = 1735, id 2244),
  so this is the real "already_exists" case with zero setup needed.
- 1 (Cowboy Bebop, 26 episodes, format TV) — confirmed NOT present in the
  local catalog, and a real, permanently-finished show whose AniList data
  won't change — the "found, not yet catalogued" case.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from main import app
from services.anilist_lookup import lookup_anilist_id
from services.anilist_sync import fetch_anilist_media_summary

NARUTO_SHIPPUDEN_ANILIST_ID = 1735
COWBOY_BEBOP_ANILIST_ID = 1
TEST_PREFIX = "__test_165__"


async def _seed_rate_limit_events(scope: str, identifier: str, count: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            for _ in range(count):
                await session.execute(
                    text("INSERT INTO rate_limit_events (scope, identifier) VALUES (:scope, :id)"),
                    {"scope": scope, "id": identifier},
                )


# httpx's ASGITransport reports this fixed client address for every request
# absent a real socket — same fact test_rate_limits_and_validation.py's own
# ANONYMOUS_IDENTIFIER constant documents.
ANONYMOUS_IDENTIFIER = "ip:127.0.0.1"


# --- fetch_anilist_media_summary: pure network-facing function ------------


@pytest.mark.asyncio
async def test_fetch_anilist_media_summary_returns_real_data_for_known_id() -> None:
    summary = await fetch_anilist_media_summary(COWBOY_BEBOP_ANILIST_ID)
    assert summary is not None
    assert summary.title == "Cowboy Bebop"
    assert summary.format == "TV"
    assert summary.episode_count == 26
    assert summary.cover_image_url is not None


@pytest.mark.asyncio
async def test_fetch_anilist_media_summary_returns_none_for_nonexistent_id() -> None:
    # Comfortably past AniList's real id space at time of writing, and
    # AniList returns `Media: null` (not an error) for an unassigned id.
    summary = await fetch_anilist_media_summary(999_999_999)
    assert summary is None


# --- lookup_anilist_id: DB-first, AniList-second service function ---------


@pytest.mark.asyncio
async def test_lookup_already_catalogued_id_never_needs_anilist_data() -> None:
    async with async_session_factory() as session:
        result = await lookup_anilist_id(session, NARUTO_SHIPPUDEN_ANILIST_ID)
    assert result.status == "already_exists"
    assert result.existing_series_id is not None
    assert result.title == "Naruto: Shippuuden"
    # Nothing AniList-sourced is populated on the already_exists branch —
    # confirms the DB check short-circuits before any live call.
    assert result.format is None
    assert result.episode_count is None


@pytest.mark.asyncio
async def test_lookup_uncatalogued_valid_id_returns_found() -> None:
    async with async_session_factory() as session:
        result = await lookup_anilist_id(session, COWBOY_BEBOP_ANILIST_ID)
    assert result.status == "found"
    assert result.title == "Cowboy Bebop"
    assert result.format == "TV"
    assert result.episode_count == 26
    assert result.cover_image_url is not None
    assert result.existing_series_id is None


@pytest.mark.asyncio
async def test_lookup_invalid_id_returns_not_found() -> None:
    async with async_session_factory() as session:
        result = await lookup_anilist_id(session, 999_999_999)
    assert result.status == "not_found"
    assert result.title is None


# --- GET /api/v1/anilist-lookup/{anilist_id} -------------------------------


@pytest.mark.asyncio
async def test_endpoint_already_exists() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/anilist-lookup/{NARUTO_SHIPPUDEN_ANILIST_ID}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "already_exists"
    assert data["existing_series_id"] is not None


@pytest.mark.asyncio
async def test_endpoint_found_new_entry() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/anilist-lookup/{COWBOY_BEBOP_ANILIST_ID}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "found"
    assert data["title"] == "Cowboy Bebop"
    assert data["episode_count"] == 26


@pytest.mark.asyncio
async def test_endpoint_not_found() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/anilist-lookup/999999999")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_found"


@pytest.mark.asyncio
async def test_endpoint_rejects_non_positive_id() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/anilist-lookup/0")
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_endpoint_rate_limited_after_threshold() -> None:
    await _seed_rate_limit_events("anilist_lookup", ANONYMOUS_IDENTIFIER, 30)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/anilist-lookup/{NARUTO_SHIPPUDEN_ANILIST_ID}")
    assert response.status_code == 429, response.text
