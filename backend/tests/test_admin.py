"""Real tests against the droplet's live Postgres — no external OAuth
provider involved, so unlike #8/#12's Turnstile/OAuth gaps, this issue's
scope is fully verifiable here.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app


def _unique_id() -> str:
    return f"test27-{uuid.uuid4().hex[:12]}"


async def _create_user(role: str = "contributor") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO users (github_id, display_name, role) "
                    "VALUES (:gh, :name, :role) RETURNING id"
                ),
                {"gh": _unique_id(), "name": "Test User", "role": role},
            )
            return result.scalar_one()


async def _create_contribution(submitted_by: int, review_status: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            series_id = (
                await session.execute(text("SELECT id FROM series LIMIT 1"))
            ).scalar_one()
            citation_id = (
                await session.execute(
                    text(
                        "INSERT INTO citations (url, description, submitted_by) "
                        "VALUES ('https://example.com', 'test citation', :uid) RETURNING id"
                    ),
                    {"uid": submitted_by},
                )
            ).scalar_one()
            await session.execute(
                text(
                    """
                    INSERT INTO contributions
                        (series_id, episode_number, proposed_status, citation_id,
                         submitted_by, review_status, license_accepted)
                    VALUES (:sid, 999001, 'canon', :cid, :uid, :status, true)
                    """
                ),
                {"sid": series_id, "cid": citation_id, "uid": submitted_by, "status": review_status},
            )


async def _cleanup(*user_ids: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM contributions WHERE submitted_by = ANY(:ids)"), {"ids": list(user_ids)}
            )
            await session.execute(
                text("DELETE FROM citations WHERE submitted_by = ANY(:ids)"), {"ids": list(user_ids)}
            )
            # Any role-update test leaves a real user.role_changed outbox
            # row as a side effect of the endpoint doing its job correctly
            # — clean it up here too, not just in the one test that
            # explicitly asserts on it, or it leaks into production
            # (real bug, caught by actually re-querying after a run, not
            # by the test suite passing).
            await session.execute(
                text(
                    "DELETE FROM outbox_events WHERE event_type = 'user.role_changed' "
                    "AND (payload->>'user_id')::int = ANY(:ids)"
                ),
                {"ids": list(user_ids)},
            )
            await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": list(user_ids)})


def _cookie(user_id: int) -> dict:
    return {SESSION_COOKIE_NAME: create_session_token(user_id)}


@pytest.mark.asyncio
async def test_list_users_requires_admin() -> None:
    contributor_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(contributor_id)) as client:
            response = await client.get("/api/v1/admin/users")
        assert response.status_code == 403
    finally:
        await _cleanup(contributor_id)


@pytest.mark.asyncio
async def test_list_users_unauthenticated_401() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_users_returns_real_stats() -> None:
    admin_id = await _create_user("admin")
    target_id = await _create_user("contributor")
    try:
        await _create_contribution(target_id, "approved")
        await _create_contribution(target_id, "approved")
        await _create_contribution(target_id, "rejected")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.get("/api/v1/admin/users", params={"limit": 100})
        assert response.status_code == 200
        body = response.json()
        target = next(u for u in body["items"] if u["id"] == target_id)
        assert target["approved_count"] == 2
        assert target["rejected_count"] == 1
        assert target["trust_score"] == 2 - (1 * 2)  # REJECTION_PENALTY = 2
    finally:
        await _cleanup(admin_id, target_id)


@pytest.mark.asyncio
async def test_role_update_requires_admin() -> None:
    moderator_id = await _create_user("moderator")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(moderator_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "moderator"})
        assert response.status_code == 403
    finally:
        await _cleanup(moderator_id, target_id)


@pytest.mark.asyncio
async def test_role_update_promotes_and_persists() -> None:
    admin_id = await _create_user("admin")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "moderator"})
        assert response.status_code == 200
        assert response.json() == {"id": target_id, "role": "moderator"}

        # Verify it actually persisted (the exact class of bug #8 caught —
        # a response that looks right within one request but was never
        # really committed).
        async with async_session_factory() as session:
            row = (
                await session.execute(text("SELECT role FROM users WHERE id = :id"), {"id": target_id})
            ).fetchone()
            assert row.role == "moderator"
    finally:
        await _cleanup(admin_id, target_id)


@pytest.mark.asyncio
async def test_role_update_rejects_invalid_role() -> None:
    admin_id = await _create_user("admin")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "superadmin"})
        assert response.status_code == 422
    finally:
        await _cleanup(admin_id, target_id)


@pytest.mark.asyncio
async def test_role_update_writes_outbox_audit_event() -> None:
    admin_id = await _create_user("admin")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "moderator"})
        assert response.status_code == 200

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_events "
                        "WHERE event_type = 'user.role_changed' "
                        "AND (payload->>'user_id')::int = :uid "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"uid": target_id},
                )
            ).fetchone()
            assert row is not None
            assert row.payload["old_role"] == "contributor"
            assert row.payload["new_role"] == "moderator"
            assert row.payload["changed_by"] == admin_id
    finally:
        await _cleanup(admin_id, target_id)  # now also handles the outbox row


@pytest.mark.asyncio
async def test_role_update_nonexistent_user_404s() -> None:
    admin_id = await _create_user("admin")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.patch("/api/v1/admin/users/999999999/role", json={"role": "moderator"})
        assert response.status_code == 404
    finally:
        await _cleanup(admin_id)


@pytest.mark.asyncio
async def test_owner_role_is_not_a_valid_promotion_target() -> None:
    """'owner' is deliberately excluded from VALID_ROLES — bootstrap-only,
    never assignable through this endpoint, not even by the owner.
    """
    admin_id = await _create_user("admin")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "owner"})
        assert response.status_code == 422
    finally:
        await _cleanup(admin_id, target_id)


@pytest.mark.asyncio
async def test_plain_admin_cannot_grant_admin_role() -> None:
    """Owner tier (decided 2026-08-21, CLAUDE.md): only the owner mints new
    admins — a plain admin can still promote/demote contributor<->moderator
    (require_admin already gates the endpoint), just not grant 'admin'
    itself.
    """
    admin_id = await _create_user("admin")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "admin"})
        assert response.status_code == 403

        async with async_session_factory() as session:
            row = (
                await session.execute(text("SELECT role FROM users WHERE id = :id"), {"id": target_id})
            ).fetchone()
            assert row.role == "contributor"  # unchanged
    finally:
        await _cleanup(admin_id, target_id)


@pytest.mark.asyncio
async def test_owner_can_grant_admin_role() -> None:
    owner_id = await _create_user("owner")
    target_id = await _create_user("contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(owner_id)) as client:
            response = await client.patch(f"/api/v1/admin/users/{target_id}/role", json={"role": "admin"})
        assert response.status_code == 200, response.text
        assert response.json() == {"id": target_id, "role": "admin"}
    finally:
        await _cleanup(owner_id, target_id)


@pytest.mark.asyncio
async def test_owner_role_cannot_be_changed_by_anyone() -> None:
    """Not even the owner can demote themselves through this endpoint —
    'owner' is immutable via the API entirely, by design (see schema.sql's
    comment on the role column).
    """
    owner_id = await _create_user("owner")
    other_owner_target = await _create_user("owner")  # simulate via direct insert, not the API
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(owner_id)) as client:
            response = await client.patch(
                f"/api/v1/admin/users/{other_owner_target}/role", json={"role": "moderator"}
            )
        assert response.status_code == 403

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT role FROM users WHERE id = :id"), {"id": other_owner_target}
                )
            ).fetchone()
            assert row.role == "owner"  # unchanged
    finally:
        await _cleanup(owner_id, other_owner_target)
