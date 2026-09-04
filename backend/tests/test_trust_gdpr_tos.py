"""Real-Postgres tests for the combined #203/#208/#209 PR:

- #203: the vote-clustering (Sybil-monitoring) report — surfaces accounts
  repeatedly endorsing each other's contributions.
- #208: GDPR right-of-access — email on GET /users/me, and the bundled
  GET /users/me/export endpoint.
- #209: account suspension — a suspended account is blocked from
  submitting/voting but keeps read/GDPR access; ToS page itself is
  covered separately in tests/test_legal.py, matching that file's own
  privacy/license test convention.

Same real-DB, test-data-prefixed, dedicated-fixture convention as
tests/test_voting.py and tests/test_admin.py.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from services.auth import Profile, login_or_create_user

TEST_PREFIX = "__test_203_208_209__"


def _unique_id() -> str:
    return f"test-tgt-{uuid.uuid4().hex[:12]}"


async def _make_user(role: str = "contributor", email: str | None = None) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session,
                "github",
                Profile(provider_id=_unique_id(), email=email, display_name="tester", avatar_url=None),
            )
            if role != "contributor":
                await session.execute(
                    text("UPDATE users SET role = :role WHERE id = :id"),
                    {"role": role, "id": user.id},
                )
            return user.id


async def _delete_user(user_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def _make_test_series(title_suffix: str) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text("INSERT INTO series (title, provenance) VALUES (:title, 'community') RETURNING id"),
                {"title": f"{TEST_PREFIX}{title_suffix}-{uuid.uuid4().hex[:8]}"},
            )
            return result.scalar_one()


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            contribution_rows = (
                await session.execute(
                    text("SELECT id, citation_id FROM contributions WHERE series_id = :sid"), {"sid": series_id}
                )
            ).all()
            contribution_ids = [r.id for r in contribution_rows]
            citation_ids = [r.citation_id for r in contribution_rows]
            # series_synonym_suggestions CASCADEs from series (schema.sql).
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if citation_ids:
                await session.execute(text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids})
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "event_type LIKE 'contribution.%' "
                        "AND (payload->>'contribution_id')::int = ANY(:ids)"
                    ),
                    {"ids": contribution_ids},
                )


async def _cleanup_proposals() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM series_proposals WHERE title LIKE :p"), {"p": f"{TEST_PREFIX}%"})


async def _cleanup_suspension_audit(*user_ids: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "DELETE FROM outbox_events WHERE event_type IN ('user.suspended', 'user.unsuspended') "
                    "AND (payload->>'user_id')::int = ANY(:ids)"
                ),
                {"ids": list(user_ids)},
            )


def _cookie(user_id: int) -> dict:
    return {SESSION_COOKIE_NAME: create_session_token(user_id)}


async def _submit_contribution_as(user_id: int, series_id: int, episode_number: int) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(user_id)) as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": series_id,
                "episode_number": episode_number,
                "proposed_status": "canon",
                "citation": {"description": f"{TEST_PREFIX} citation"},
                "license_accepted": True,
            },
        )
    return response


async def _vote_as(user_id: int, contribution_id: int, vote: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(user_id)) as client:
        return await client.post(f"/api/v1/contributions/{contribution_id}/vote", json={"vote": vote})


async def _suspend(admin_id: int, target_id: int, *, suspended: bool, reason: str | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(admin_id)) as client:
        return await client.patch(
            f"/api/v1/admin/users/{target_id}/suspension",
            json={"suspended": suspended, "reason": reason},
        )


# ---------------------------------------------------------------------------
# #208: GDPR right-of-access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_users_me_includes_email() -> None:
    user_id = await _make_user(email="tester@example.com")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(user_id)) as client:
            response = await client.get("/api/v1/users/me")
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "tester@example.com"
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_users_me_export_bundles_everything() -> None:
    caller_id = await _make_user(email="caller@example.com")
    other_id = await _make_user()
    series_id = await _make_test_series("export")
    try:
        # Caller submits a contribution.
        contrib_resp = await _submit_contribution_as(caller_id, series_id, 1)
        assert contrib_resp.status_code == 201, contrib_resp.text

        # Other user submits a contribution the caller then votes on.
        other_contrib_resp = await _submit_contribution_as(other_id, series_id, 2)
        assert other_contrib_resp.status_code == 201, other_contrib_resp.text
        other_contrib_id = other_contrib_resp.json()["id"]
        vote_resp = await _vote_as(caller_id, other_contrib_id, "endorse")
        assert vote_resp.status_code == 200, vote_resp.text

        # Caller proposes a series and suggests a synonym.
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(caller_id)) as client:
            proposal_resp = await client.post(
                "/api/v1/series-proposals",
                json={
                    "title": f"{TEST_PREFIX}proposal-{uuid.uuid4().hex[:8]}",
                    "justification": f"{TEST_PREFIX} justification",
                    "license_accepted": True,
                },
            )
            assert proposal_resp.status_code == 201, proposal_resp.text

            synonym_resp = await client.post(
                "/api/v1/synonym-suggestions",
                json={
                    "series_id": series_id,
                    "synonym": f"{TEST_PREFIX} synonym",
                    "license_accepted": True,
                },
            )
            assert synonym_resp.status_code == 201, synonym_resp.text

            export_resp = await client.get("/api/v1/users/me/export")
        assert export_resp.status_code == 200, export_resp.text
        body = export_resp.json()

        assert body["profile"]["id"] == caller_id
        assert body["profile"]["email"] == "caller@example.com"
        assert len(body["contributions"]) == 1
        assert body["contributions"][0]["episode_number"] == 1
        assert len(body["votes"]) == 1
        assert body["votes"][0]["contribution_id"] == other_contrib_id
        assert len(body["series_proposals"]) == 1
        assert body["series_proposals"][0]["title"].startswith(f"{TEST_PREFIX}proposal-")
        assert len(body["synonym_suggestions"]) == 1
        assert body["synonym_suggestions"][0]["synonym"] == f"{TEST_PREFIX} synonym"
    finally:
        await _cleanup_series(series_id)
        await _cleanup_proposals()
        await _delete_user(caller_id)
        await _delete_user(other_id)


@pytest.mark.asyncio
async def test_users_me_export_requires_authentication() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/users/me/export")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# #209: account suspension
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspension_endpoint_requires_admin() -> None:
    contributor_id = await _make_user()
    target_id = await _make_user()
    try:
        response = await _suspend(contributor_id, target_id, suspended=True)
        assert response.status_code == 403
    finally:
        await _delete_user(contributor_id)
        await _delete_user(target_id)


@pytest.mark.asyncio
async def test_suspend_and_unsuspend_roundtrip() -> None:
    admin_id = await _make_user(role="admin")
    target_id = await _make_user()
    try:
        suspend_resp = await _suspend(admin_id, target_id, suspended=True, reason="__test__ spam")
        assert suspend_resp.status_code == 200, suspend_resp.text
        body = suspend_resp.json()
        assert body["suspended"] is True
        assert body["suspended_at"] is not None
        assert body["suspended_reason"] == "__test__ spam"

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT suspended_at, suspended_reason FROM users WHERE id = :id"), {"id": target_id}
                )
            ).fetchone()
            assert row.suspended_at is not None
            assert row.suspended_reason == "__test__ spam"

        unsuspend_resp = await _suspend(admin_id, target_id, suspended=False)
        assert unsuspend_resp.status_code == 200, unsuspend_resp.text
        body = unsuspend_resp.json()
        assert body["suspended"] is False
        assert body["suspended_at"] is None
        assert body["suspended_reason"] is None

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT suspended_at, suspended_reason FROM users WHERE id = :id"), {"id": target_id}
                )
            ).fetchone()
            assert row.suspended_at is None
            assert row.suspended_reason is None
    finally:
        await _cleanup_suspension_audit(target_id)
        await _delete_user(admin_id)
        await _delete_user(target_id)


@pytest.mark.asyncio
async def test_owner_cannot_be_suspended() -> None:
    admin_id = await _make_user(role="admin")
    owner_id = await _make_user(role="owner")
    try:
        response = await _suspend(admin_id, owner_id, suspended=True)
        assert response.status_code == 403
    finally:
        await _delete_user(admin_id)
        await _delete_user(owner_id)


@pytest.mark.asyncio
async def test_suspend_nonexistent_user_404s() -> None:
    admin_id = await _make_user(role="admin")
    try:
        response = await _suspend(admin_id, 999999999, suspended=True)
        assert response.status_code == 404
    finally:
        await _delete_user(admin_id)


@pytest.mark.asyncio
async def test_suspended_user_cannot_submit_contribution() -> None:
    admin_id = await _make_user(role="admin")
    target_id = await _make_user()
    series_id = await _make_test_series("suspend-submit")
    try:
        suspend_resp = await _suspend(admin_id, target_id, suspended=True, reason="__test__")
        assert suspend_resp.status_code == 200

        response = await _submit_contribution_as(target_id, series_id, 1)
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_suspension_audit(target_id)
        await _cleanup_series(series_id)
        await _delete_user(admin_id)
        await _delete_user(target_id)


@pytest.mark.asyncio
async def test_suspended_user_cannot_vote() -> None:
    admin_id = await _make_user(role="admin")
    submitter_id = await _make_user()
    voter_id = await _make_user()
    series_id = await _make_test_series("suspend-vote")
    try:
        contrib_resp = await _submit_contribution_as(submitter_id, series_id, 1)
        assert contrib_resp.status_code == 201, contrib_resp.text
        contribution_id = contrib_resp.json()["id"]

        suspend_resp = await _suspend(admin_id, voter_id, suspended=True, reason="__test__")
        assert suspend_resp.status_code == 200

        response = await _vote_as(voter_id, contribution_id, "endorse")
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_suspension_audit(voter_id)
        await _cleanup_series(series_id)
        await _delete_user(admin_id)
        await _delete_user(submitter_id)
        await _delete_user(voter_id)


@pytest.mark.asyncio
async def test_suspended_user_keeps_read_and_gdpr_access() -> None:
    """#209's own scope note: suspension blocks submit/vote, never reading
    or the GDPR-rights endpoints (GET /users/me, GET /users/me/export,
    DELETE /users/me).
    """
    admin_id = await _make_user(role="admin")
    target_id = await _make_user(email="suspended@example.com")
    try:
        suspend_resp = await _suspend(admin_id, target_id, suspended=True, reason="__test__")
        assert suspend_resp.status_code == 200

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(target_id)) as client:
            me_resp = await client.get("/api/v1/users/me")
            assert me_resp.status_code == 200
            assert me_resp.json()["email"] == "suspended@example.com"

            export_resp = await client.get("/api/v1/users/me/export")
            assert export_resp.status_code == 200

            delete_resp = await client.delete("/api/v1/users/me")
            assert delete_resp.status_code == 204
        target_id = None  # deleted by the request above, not by the finally block
    finally:
        await _delete_user(admin_id)
        if target_id:
            await _cleanup_suspension_audit(target_id)
            await _delete_user(target_id)


# ---------------------------------------------------------------------------
# #203: vote-clustering (Sybil-monitoring) report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vote_clustering_report_requires_moderator() -> None:
    contributor_id = await _make_user()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(contributor_id)
        ) as client:
            response = await client.get("/api/v1/admin/vote-clustering-report")
        assert response.status_code == 403
    finally:
        await _delete_user(contributor_id)


@pytest.mark.asyncio
async def test_vote_clustering_report_surfaces_reciprocal_pairs() -> None:
    moderator_id = await _make_user(role="moderator")
    user_a = await _make_user()
    user_b = await _make_user()
    series_id = await _make_test_series("clustering")
    try:
        # A submits two contributions, B endorses both.
        a_contrib_1 = (await _submit_contribution_as(user_a, series_id, 1)).json()["id"]
        a_contrib_2 = (await _submit_contribution_as(user_a, series_id, 2)).json()["id"]
        assert (await _vote_as(user_b, a_contrib_1, "endorse")).status_code == 200
        assert (await _vote_as(user_b, a_contrib_2, "endorse")).status_code == 200

        # B submits two contributions, A endorses both — the reciprocal half.
        b_contrib_1 = (await _submit_contribution_as(user_b, series_id, 3)).json()["id"]
        b_contrib_2 = (await _submit_contribution_as(user_b, series_id, 4)).json()["id"]
        assert (await _vote_as(user_a, b_contrib_1, "endorse")).status_code == 200
        assert (await _vote_as(user_a, b_contrib_2, "endorse")).status_code == 200

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(moderator_id)
        ) as client:
            response = await client.get("/api/v1/admin/vote-clustering-report", params={"min_reciprocal_count": 2})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["min_reciprocal_count"] == 2

        pair = next(
            item
            for item in body["items"]
            if {item["user_a_id"], item["user_b_id"]} == {user_a, user_b}
        )
        assert pair["a_endorsed_b_count"] == 2
        assert pair["b_endorsed_a_count"] == 2
        assert pair["combined_endorsement_count"] == 4
    finally:
        await _cleanup_series(series_id)
        await _delete_user(moderator_id)
        await _delete_user(user_a)
        await _delete_user(user_b)


@pytest.mark.asyncio
async def test_vote_clustering_report_excludes_one_directional_endorsement() -> None:
    """A single account endorsing another's submissions with no reciprocal
    endorsement back is normal, everyday voting — not clustering — and
    must not show up as a pair.
    """
    moderator_id = await _make_user(role="moderator")
    user_a = await _make_user()
    user_b = await _make_user()
    series_id = await _make_test_series("clustering-onedir")
    try:
        a_contrib_1 = (await _submit_contribution_as(user_a, series_id, 1)).json()["id"]
        a_contrib_2 = (await _submit_contribution_as(user_a, series_id, 2)).json()["id"]
        assert (await _vote_as(user_b, a_contrib_1, "endorse")).status_code == 200
        assert (await _vote_as(user_b, a_contrib_2, "endorse")).status_code == 200
        # user_a never endorses anything of user_b's — no reciprocal half.

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=_cookie(moderator_id)
        ) as client:
            response = await client.get("/api/v1/admin/vote-clustering-report", params={"min_reciprocal_count": 2})
        assert response.status_code == 200, response.text
        body = response.json()
        assert not any({item["user_a_id"], item["user_b_id"]} == {user_a, user_b} for item in body["items"])
    finally:
        await _cleanup_series(series_id)
        await _delete_user(moderator_id)
        await _delete_user(user_a)
        await _delete_user(user_b)
