"""Real-Postgres tests for #150 (title-similarity duplicate-series
detection on the series-proposal submission flow, no-ID path). Same
convention as this project's other test files: exercise the real app
against the real test-pg, prefix test data, clean up everything inserted.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from main import app
from services.series_similarity import normalize_title

TEST_PREFIX = "__test_150__"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_series(title: str) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text("INSERT INTO series (title, provenance) VALUES (:title, 'community') RETURNING id"),
                {"title": title},
            )
            return result.scalar_one()


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})


async def _cleanup_series_proposal_by_title(title: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM series_proposals WHERE title = :title"), {"title": title}
            )


# --- normalize_title: pure-function unit tests -----------------------------


def test_normalize_title_lowercases_and_strips_punctuation() -> None:
    assert normalize_title("Naruto: Shippuuden!") == "naruto shippuuden"


def test_normalize_title_collapses_whitespace() -> None:
    assert normalize_title("  Naruto   Shippuuden  ") == "naruto shippuuden"


def test_normalize_title_matches_across_case_and_punctuation() -> None:
    assert normalize_title("naruto shippuuden") == normalize_title("Naruto: Shippuuden!")


def test_normalize_title_of_pure_punctuation_is_empty() -> None:
    assert normalize_title("!!!") == ""


# --- GET /series-proposals/check-title -------------------------------------


@pytest.mark.asyncio
async def test_check_title_finds_exact_normalized_match() -> None:
    title = f"{TEST_PREFIX}Exact Match Show"
    series_id = await _make_series(title)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/series-proposals/check-title",
                params={"title": f"  {title.upper()}!!  "},
            )
        assert response.status_code == 200, response.text
        matches = response.json()["matches"]
        assert any(m["id"] == series_id for m in matches)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_check_title_finds_superstring_match() -> None:
    """"Naruto" should surface "Naruto: Shippuuden"-shaped catalog entries
    as a possible (non-blocking) match — the realistic case this issue
    exists for."""
    title = f"{TEST_PREFIX}Watashi"
    series_id = await _make_series(f"{title}: Shippuuden")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/series-proposals/check-title", params={"title": title}
            )
        assert response.status_code == 200, response.text
        matches = response.json()["matches"]
        assert any(m["id"] == series_id for m in matches)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_check_title_no_match_for_genuinely_distinct_title() -> None:
    await _make_series(f"{TEST_PREFIX}Alpha Show")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/series-proposals/check-title",
                params={"title": f"{TEST_PREFIX}Completely Unrelated Title Zeta"},
            )
        assert response.status_code == 200, response.text
        assert response.json()["matches"] == []
    finally:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("DELETE FROM series WHERE title = :title"),
                    {"title": f"{TEST_PREFIX}Alpha Show"},
                )


@pytest.mark.asyncio
async def test_check_title_blank_title_returns_no_matches_and_no_error() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/series-proposals/check-title", params={"title": "   "})
    assert response.status_code == 200, response.text
    assert response.json()["matches"] == []


# --- POST /series-proposals surfaces possible_duplicate_matches ------------


@pytest.mark.asyncio
async def test_submit_proposal_with_near_duplicate_title_surfaces_warning() -> None:
    existing_title = f"{TEST_PREFIX}Bleach Alt"
    series_id = await _make_series(existing_title)
    proposal_title = f"{existing_title}!!!"
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/series-proposals",
                json={
                    "title": proposal_title,
                    "justification": f"{TEST_PREFIX} justification",
                    "license_accepted": True,
                },
            )
        assert response.status_code == 201, response.text
        data = response.json()
        assert any(m["id"] == series_id for m in data["possible_duplicate_matches"])
    finally:
        await _cleanup_series_proposal_by_title(proposal_title)
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_submit_proposal_with_distinct_title_has_zero_behavior_change() -> None:
    """A proposal whose title matches nothing existing proceeds exactly as
    it did before #150 — 201, empty possible_duplicate_matches, no other
    change to the response shape or the write itself."""
    title = f"{TEST_PREFIX}{_unique_id()} Wholly Original Show"
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/series-proposals",
                json={
                    "title": title,
                    "justification": f"{TEST_PREFIX} justification",
                    "license_accepted": True,
                },
            )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["possible_duplicate_matches"] == []
        assert data["title"] == title
        assert data["review_status"] == "pending"
    finally:
        await _cleanup_series_proposal_by_title(title)


@pytest.mark.asyncio
async def test_pending_proposal_listing_carries_fresh_duplicate_hint() -> None:
    """The moderation queue (GET /series-proposals, moderator-only) must
    surface the same hint, computed fresh against the CURRENT catalog —
    confirmed here by creating the matching series AFTER the proposal was
    submitted, then checking the listing still finds it."""
    from core.security import SESSION_COOKIE_NAME, create_session_token
    from services.auth import Profile, login_or_create_user

    async def _make_moderator() -> int:
        async with async_session_factory() as session:
            async with session.begin():
                user = await login_or_create_user(
                    session,
                    "github",
                    Profile(provider_id=_unique_id(), email=None, display_name="mod", avatar_url=None),
                )
                await session.execute(
                    text("UPDATE users SET role = 'moderator' WHERE id = :id"), {"id": user.id}
                )
                return user.id

    proposal_title = f"{TEST_PREFIX}Later Matched Show"
    moderator_id = await _make_moderator()
    series_id: int | None = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            submit_response = await client.post(
                "/api/v1/series-proposals",
                json={
                    "title": proposal_title,
                    "justification": f"{TEST_PREFIX} justification",
                    "license_accepted": True,
                },
            )
            assert submit_response.status_code == 201, submit_response.text
            # No matching series exists yet at submission time.
            assert submit_response.json()["possible_duplicate_matches"] == []

            series_id = await _make_series(proposal_title)

            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
            list_response = await client.get("/api/v1/series-proposals")
        assert list_response.status_code == 200, list_response.text
        proposal_row = next(p for p in list_response.json() if p["title"] == proposal_title)
        assert any(m["id"] == series_id for m in proposal_row["possible_duplicate_matches"])
    finally:
        await _cleanup_series_proposal_by_title(proposal_title)
        if series_id is not None:
            await _cleanup_series(series_id)
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": moderator_id})
