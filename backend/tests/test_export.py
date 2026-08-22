"""Real-Postgres tests for #22's export access gate. Uses recognizable
test-prefixed data and cleans up everything it inserts — safe to run
against a database that already has real data loaded (e.g. #4's bootstrap
import, or other agents' work), since nothing here touches a row it
didn't create itself.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import hash_api_key
from main import app

TEST_PREFIX = "__test_22__"
TEST_EMAIL = f"{TEST_PREFIX}@example.com"


async def _cleanup_key(email: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM export_api_keys WHERE email = :email"),
                {"email": email},
            )


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM episodes WHERE series_id = :sid"), {"sid": series_id}
            )
            await session.execute(text("DELETE FROM series WHERE id = :sid"), {"sid": series_id})


async def _insert_test_series_with_episode() -> tuple[int, int]:
    async with async_session_factory() as session:
        async with session.begin():
            series_id = (
                await session.execute(
                    text(
                        "INSERT INTO series (title, provenance) "
                        "VALUES (:title, 'community') RETURNING id"
                    ),
                    {"title": f"{TEST_PREFIX} Series"},
                )
            ).scalar_one()
            citation_id = (
                await session.execute(
                    text(
                        "INSERT INTO citations (url, description) "
                        "VALUES ('https://example.com', :desc) RETURNING id"
                    ),
                    {"desc": f"{TEST_PREFIX} citation"},
                )
            ).scalar_one()
            contribution_id = (
                await session.execute(
                    text(
                        "INSERT INTO contributions "
                        "(series_id, episode_number, proposed_status, citation_id, "
                        "license_accepted, review_status) "
                        "VALUES (:sid, 1, 'canon', :cid, true, 'approved') RETURNING id"
                    ),
                    {"sid": series_id, "cid": citation_id},
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO episodes "
                    "(series_id, episode_number, status, citation_id, approved_contribution_id) "
                    "VALUES (:sid, 1, 'canon', :cid, :contrib_id)"
                ),
                {"sid": series_id, "cid": citation_id, "contrib_id": contribution_id},
            )
    return series_id, citation_id


@pytest.mark.asyncio
async def test_request_access_with_acceptance_issues_key_and_stores_record() -> None:
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/export/request-access",
                json={"email": TEST_EMAIL, "license_accepted": True},
            )
        assert response.status_code == 200
        key = response.json()["api_key"]
        assert key.startswith("afp_export_")

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT email, license_accepted, terms_version, key_hash "
                        "FROM export_api_keys WHERE email = :email"
                    ),
                    {"email": TEST_EMAIL},
                )
            ).one()
            assert row.email == TEST_EMAIL
            assert row.license_accepted is True
            assert row.terms_version == "cc-by-nc-sa-4.0-2026-08-21"
            # Plaintext key is never stored — only its hash.
            assert row.key_hash == hash_api_key(key)
            assert row.key_hash != key
    finally:
        await _cleanup_key(TEST_EMAIL)


@pytest.mark.asyncio
async def test_request_access_without_acceptance_is_rejected_and_stores_nothing() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/export/request-access",
            json={"email": TEST_EMAIL, "license_accepted": False},
        )
    assert response.status_code == 400

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT id FROM export_api_keys WHERE email = :email"),
                {"email": TEST_EMAIL},
            )
        ).first()
        assert row is None


@pytest.mark.asyncio
async def test_export_without_key_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/export")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_with_invalid_key_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/export", headers={"X-API-Key": "afp_export_not-a-real-key"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_with_revoked_key_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        access_response = await client.post(
            "/api/v1/export/request-access",
            json={"email": TEST_EMAIL, "license_accepted": True},
        )
    key = access_response.json()["api_key"]

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE export_api_keys SET revoked_at = now() WHERE email = :email"
                ),
                {"email": TEST_EMAIL},
            )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/export", headers={"X-API-Key": key})
        assert response.status_code == 401
    finally:
        await _cleanup_key(TEST_EMAIL)


@pytest.mark.asyncio
async def test_export_with_valid_key_returns_full_dataset_with_manifest() -> None:
    series_id, _citation_id = await _insert_test_series_with_episode()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            access_response = await client.post(
                "/api/v1/export/request-access",
                json={"email": TEST_EMAIL, "license_accepted": True},
            )
            key = access_response.json()["api_key"]

            export_response = await client.get(
                "/api/v1/export", headers={"X-API-Key": key}
            )
        assert export_response.status_code == 200
        body = export_response.json()

        assert body["manifest"]["license"] == "CC BY-NC-SA 4.0"
        assert "CC BY-NC-SA" in body["manifest"]["attribution_notice"]

        matching = [s for s in body["series"] if s["series_id"] == series_id]
        assert len(matching) == 1
        series_out = matching[0]
        assert series_out["title"] == f"{TEST_PREFIX} Series"
        assert len(series_out["episodes"]) == 1
        assert series_out["episodes"][0]["episode_number"] == 1
        assert series_out["episodes"][0]["status"] == "canon"
    finally:
        await _cleanup_key(TEST_EMAIL)
        await _cleanup_series(series_id)


async def _cleanup_key_by_hash(key: str) -> None:
    """Revoke tests empty out `email` as part of what they're testing, so
    the other tests' `_cleanup_key` (WHERE email = ...) can't find the row
    afterward — clean up by key_hash instead.
    """
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM export_api_keys WHERE key_hash = :h"),
                {"h": hash_api_key(key)},
            )


@pytest.mark.asyncio
async def test_revoke_forgets_email_and_invalidates_key() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        access_response = await client.post(
            "/api/v1/export/request-access",
            json={"email": TEST_EMAIL, "license_accepted": True},
        )
        key = access_response.json()["api_key"]
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            revoke_response = await client.post(
                "/api/v1/export/revoke", headers={"X-API-Key": key}
            )
            assert revoke_response.status_code == 204

            # The key no longer works...
            export_response = await client.get(
                "/api/v1/export", headers={"X-API-Key": key}
            )
            assert export_response.status_code == 401

        # ...and the email is actually gone from the row, not just the key
        # disabled — the whole point of this endpoint per #46.
        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT email, revoked_at FROM export_api_keys WHERE key_hash = :h"),
                    {"h": hash_api_key(key)},
                )
            ).one()
            assert row.email == ""
            assert row.revoked_at is not None
    finally:
        await _cleanup_key_by_hash(key)


@pytest.mark.asyncio
async def test_revoke_is_idempotent_on_an_already_revoked_key() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        access_response = await client.post(
            "/api/v1/export/request-access",
            json={"email": TEST_EMAIL, "license_accepted": True},
        )
        key = access_response.json()["api_key"]
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/v1/export/revoke", headers={"X-API-Key": key})
            assert first.status_code == 204
            second = await client.post("/api/v1/export/revoke", headers={"X-API-Key": key})
            assert second.status_code == 204
    finally:
        await _cleanup_key_by_hash(key)


@pytest.mark.asyncio
async def test_revoke_unknown_key_404s() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/export/revoke", headers={"X-API-Key": "afp_export_not-a-real-key"}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_without_key_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/export/revoke")
    assert response.status_code == 401
