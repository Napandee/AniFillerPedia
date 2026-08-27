"""Real-Postgres tests for #139 (anonymous write-endpoint rate limiting),
#140 (max_length on freeform text fields), and #141 (export email
validation + rate limit) — grouped in one file since they're one PR's
worth of related anonymous/public write-endpoint hardening. Same
conventions as the rest of this test suite: exercise the real app against
the real test-pg, prefix test data, clean up everything inserted.

Note: tests/conftest.py's `_clear_rate_limit_events` autouse fixture wipes
`rate_limit_events` before every test in this whole suite, so seeding rows
directly here (mirroring test_bulk_contributions.py's own
bulk_submission_events seeding pattern) is isolated from whatever any
other test file's own anonymous submissions did.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from services.auth import Profile, login_or_create_user

TEST_PREFIX = "__test_139__"

# httpx's ASGITransport reports this fixed client address for every
# request unless a real network socket is involved (confirmed directly:
# request.client == ("127.0.0.1", 123)) — so every anonymous test client
# in this whole suite shares this identifier, which is exactly why the
# conftest.py fixture above exists.
ANONYMOUS_IDENTIFIER = "ip:127.0.0.1"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_authenticated_user() -> int:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session,
                "github",
                Profile(provider_id=_unique_id(), email=None, display_name="tester", avatar_url=None),
            )
            return user.id


async def _delete_user(user_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def _make_test_series(title_suffix: str = "") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO series (title, provenance) "
                    "VALUES (:title, 'community') RETURNING id"
                ),
                {"title": f"{TEST_PREFIX}series{title_suffix}"},
            )
            return result.scalar_one()


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    text("SELECT id, citation_id FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).all()
            citation_ids = [r.citation_id for r in rows]
            contribution_ids = [r.id for r in rows]
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if citation_ids:
                await session.execute(
                    text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids}
                )
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE event_type = 'contribution.submitted' "
                        "AND (payload->>'contribution_id')::int = ANY(:ids)"
                    ),
                    {"ids": contribution_ids},
                )


async def _seed_rate_limit_events(scope: str, identifier: str, count: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            for _ in range(count):
                await session.execute(
                    text("INSERT INTO rate_limit_events (scope, identifier) VALUES (:scope, :id)"),
                    {"scope": scope, "id": identifier},
                )


async def _cleanup_series_proposals(title: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM series_proposals WHERE title = :title"), {"title": title}
            )


# ---------------------------------------------------------------------
# #139 — single-episode POST /contributions rate limit
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contribution_submit_rate_limit_blocks_anonymous_after_threshold() -> None:
    await _seed_rate_limit_events("contribution_submit", ANONYMOUS_IDENTIFIER, 20)
    series_id = await _make_test_series("RateLimit")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 1,
                    "proposed_status": "canon",
                    "citation": {"description": f"{TEST_PREFIX} citation"},
                    "license_accepted": True,
                },
            )
        assert response.status_code == 429, response.text
        assert "20 contribution submissions" in response.json()["detail"]

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).scalar_one()
            assert count == 0  # rejected before any write
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_contribution_submit_rate_limit_is_scoped_per_identifier() -> None:
    """An authenticated user hitting their OWN limit doesn't affect a
    different anonymous caller's budget, and vice versa — proves
    get_rate_limit_identifier's user-id vs. IP split actually isolates
    the two, not just a single shared global counter.
    """
    user_id = await _make_authenticated_user()
    await _seed_rate_limit_events("contribution_submit", f"user:{user_id}", 20)
    series_id = await _make_test_series("PerIdentifier")
    try:
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as authed_client:
            authed_client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
            blocked = await authed_client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 1,
                    "proposed_status": "canon",
                    "citation": {"description": f"{TEST_PREFIX} citation"},
                    "license_accepted": True,
                },
            )
        assert blocked.status_code == 429, blocked.text

        # A different (anonymous) caller is unaffected by that user's limit.
        async with AsyncClient(transport=transport, base_url="http://test") as anon_client:
            allowed = await anon_client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 2,
                    "proposed_status": "canon",
                    "citation": {"description": f"{TEST_PREFIX} citation"},
                    "license_accepted": True,
                },
            )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _cleanup_series(series_id)
        await _delete_user(user_id)


# ---------------------------------------------------------------------
# #139 — POST /series-proposals with attached episode_data rate limit
# ---------------------------------------------------------------------


def _episode_data_payload() -> dict:
    return {
        "canon_ranges": "1-2",
        "citation": {"description": f"{TEST_PREFIX} episode-data citation"},
    }


@pytest.mark.asyncio
async def test_series_proposal_bulk_anonymous_rate_limit_blocks_after_threshold() -> None:
    """The confirmed #139 finding: an anonymous series-proposal submission
    with attached episode_data previously had NO rate limit at all, unlike
    the direct bulk-contribution endpoint. This is the fix, tested via the
    anonymous IP-keyed counter (services/series_proposals.py).
    """
    await _seed_rate_limit_events("series_proposal_bulk_anonymous", ANONYMOUS_IDENTIFIER, 10)
    title = f"{TEST_PREFIX}AnonBulkLimited"
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/series-proposals",
                json={
                    "title": title,
                    "justification": f"{TEST_PREFIX} justification",
                    "license_accepted": True,
                    "episode_data": _episode_data_payload(),
                },
            )
        assert response.status_code == 429, response.text
        assert "bulk-episode-data submissions" in response.json()["detail"]

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM series_proposals WHERE title = :title"),
                    {"title": title},
                )
            ).scalar_one()
            assert count == 0  # rejected before any write
    finally:
        await _cleanup_series_proposals(title)


@pytest.mark.asyncio
async def test_series_proposal_bulk_authenticated_shares_84_limit() -> None:
    """Authenticated callers are counted against the SAME
    bulk_submission_events table #84 built for the direct bulk-
    contribution endpoint — reused directly, not a parallel mechanism,
    per #139's own guidance.
    """
    user_id = await _make_authenticated_user()
    async with async_session_factory() as session:
        async with session.begin():
            for _ in range(10):
                await session.execute(
                    text("INSERT INTO bulk_submission_events (submitted_by) VALUES (:uid)"),
                    {"uid": user_id},
                )

    title = f"{TEST_PREFIX}AuthedBulkLimited"
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
            response = await client.post(
                "/api/v1/series-proposals",
                json={
                    "title": title,
                    "justification": f"{TEST_PREFIX} justification",
                    "license_accepted": True,
                    "episode_data": _episode_data_payload(),
                },
            )
        assert response.status_code == 429, response.text

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM series_proposals WHERE title = :title"),
                    {"title": title},
                )
            ).scalar_one()
            assert count == 0
    finally:
        await _cleanup_series_proposals(title)
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_series_proposal_without_episode_data_is_never_rate_limited_by_bulk_check() -> None:
    """A plain series proposal (no attached episode data) never touches
    the bulk-episode-data limiter at all — confirmed here by seeding it
    already at the cap and checking a plain proposal still succeeds.
    """
    await _seed_rate_limit_events("series_proposal_bulk_anonymous", ANONYMOUS_IDENTIFIER, 10)
    title = f"{TEST_PREFIX}NoEpisodeData"
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
    finally:
        await _cleanup_series_proposals(title)


# ---------------------------------------------------------------------
# #140 — max_length on freeform text fields
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_citation_description_over_max_length_rejected() -> None:
    series_id = await _make_test_series("LongDescription")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 1,
                    "proposed_status": "canon",
                    "citation": {"description": "x" * 3001},
                    "license_accepted": True,
                },
            )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_citation_methodology_note_over_max_length_rejected() -> None:
    series_id = await _make_test_series("LongMethodologyNote")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 1,
                    "proposed_status": "canon",
                    "citation": {
                        "description": f"{TEST_PREFIX} citation",
                        "methodology_note": "x" * 5001,
                    },
                    "license_accepted": True,
                },
            )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_proposed_note_over_max_length_rejected() -> None:
    series_id = await _make_test_series("LongProposedNote")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 1,
                    "proposed_status": "canon",
                    "proposed_note": "x" * 3001,
                    "citation": {"description": f"{TEST_PREFIX} citation"},
                    "license_accepted": True,
                },
            )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_proposal_justification_over_max_length_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": f"{TEST_PREFIX}LongJustification",
                "justification": "x" * 3001,
                "license_accepted": True,
            },
        )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_fields_at_exactly_max_length_are_accepted() -> None:
    """Boundary check — max_length rejects over the limit, not AT it."""
    series_id = await _make_test_series("ExactlyMaxLength")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/contributions",
                json={
                    "series_id": series_id,
                    "episode_number": 1,
                    "proposed_status": "canon",
                    "proposed_note": "x" * 3000,
                    "citation": {
                        "description": "x" * 3000,
                        "methodology_note": "x" * 5000,
                    },
                    "license_accepted": True,
                },
            )
        assert response.status_code == 201, response.text
    finally:
        await _cleanup_series(series_id)


# ---------------------------------------------------------------------
# #141 — export email validation + rate limit
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_request_access_malformed_email_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/export/request-access",
            json={"email": "not-an-email", "license_accepted": True},
        )
    assert response.status_code == 422, response.text

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT id FROM export_api_keys WHERE email = :email"),
                {"email": "not-an-email"},
            )
        ).first()
        assert row is None


@pytest.mark.asyncio
async def test_export_request_access_rate_limit_blocks_after_threshold() -> None:
    await _seed_rate_limit_events("export_request_access", ANONYMOUS_IDENTIFIER, 5)
    email = f"{TEST_PREFIX}ratelimit@example.com"
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/export/request-access",
                json={"email": email, "license_accepted": True},
            )
        assert response.status_code == 429, response.text
        assert "export API keys" in response.json()["detail"]

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT id FROM export_api_keys WHERE email = :email"),
                    {"email": email},
                )
            ).first()
            assert row is None  # rejected before any write
    finally:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("DELETE FROM export_api_keys WHERE email = :email"), {"email": email}
                )
