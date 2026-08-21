"""Tests split deliberately into two groups (see report to the user):

- Real, against the droplet's live Postgres: admin bootstrap, explicit-
  link-only enforcement (including the conflict-rejection case), session
  cookie issuance/verification, state CSRF checks, /users/me, the full
  authorize->callback->me round trip end to end.
- NOT verifiable here: an actual code exchange against GitHub/Discord's
  real OAuth servers — those credentials don't exist yet (#25). Every test
  that reaches exchange_code_for_token/fetch_provider_profile monkeypatches
  them with a fake-but-realistic response shape instead of hitting a
  live provider.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import verify_session_token
from main import app
from repositories.users import find_by_provider_id
from services.auth import AccountLinkConflict, Profile, link_provider_to_current_user, login_or_create_user


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _delete_user_by_github_id(github_id: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM users WHERE github_id = :id"), {"id": github_id}
            )


# ---------------------------------------------------------------------------
# services.auth — real DB, no HTTP involved at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_creates_contributor_by_default() -> None:
    gh_id = _unique_id()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await login_or_create_user(
                    session,
                    "github",
                    Profile(provider_id=gh_id, email=None, display_name="tester", avatar_url=None),
                )
            assert user.role == "contributor"
            assert user.github_id == gh_id
    finally:
        await _delete_user_by_github_id(gh_id)


@pytest.mark.asyncio
async def test_login_second_time_reuses_same_account_not_a_new_one() -> None:
    gh_id = _unique_id()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                first = await login_or_create_user(
                    session, "github", Profile(provider_id=gh_id, email=None, display_name=None, avatar_url=None)
                )
        async with async_session_factory() as session:
            async with session.begin():
                second = await login_or_create_user(
                    session, "github", Profile(provider_id=gh_id, email=None, display_name=None, avatar_url=None)
                )
        assert first.id == second.id
    finally:
        await _delete_user_by_github_id(gh_id)


@pytest.mark.asyncio
async def test_owner_bootstrap_via_env_var_not_first_user_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """The actual Guardrail this project cares about: role is granted
    because the id matches INITIAL_ADMIN_GITHUB_ID, never because of
    signup order. The granted role is 'owner' (decided 2026-08-21, CLAUDE.md)
    — the bootstrap identity is the distinct top tier, not just 'admin'.
    """
    from core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("INITIAL_ADMIN_GITHUB_ID", "the-real-admin")
    get_settings.cache_clear()

    ordinary_id = _unique_id()
    admin_id = "the-real-admin-" + _unique_id()  # won't match on purpose first
    try:
        async with async_session_factory() as session:
            async with session.begin():
                ordinary = await login_or_create_user(
                    session, "github", Profile(provider_id=ordinary_id, email=None, display_name=None, avatar_url=None)
                )
        assert ordinary.role == "contributor", "signing up first must never grant admin"
    finally:
        await _delete_user_by_github_id(ordinary_id)
        get_settings.cache_clear()

    monkeypatch.setenv("INITIAL_ADMIN_GITHUB_ID", admin_id)
    get_settings.cache_clear()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await login_or_create_user(
                    session, "github", Profile(provider_id=admin_id, email=None, display_name=None, avatar_url=None)
                )
        assert admin.role == "owner"
    finally:
        await _delete_user_by_github_id(admin_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_link_provider_attaches_to_existing_user() -> None:
    gh_id = _unique_id()
    discord_id = _unique_id()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await login_or_create_user(
                    session, "github", Profile(provider_id=gh_id, email=None, display_name=None, avatar_url=None)
                )
        async with async_session_factory() as session:
            async with session.begin():
                await link_provider_to_current_user(
                    session,
                    current_user_id=user.id,
                    provider="discord",
                    profile=Profile(provider_id=discord_id, email=None, display_name=None, avatar_url=None),
                )
        async with async_session_factory() as session:
            linked = await find_by_provider_id(session, "discord", discord_id)
            assert linked is not None
            assert linked.id == user.id
    finally:
        await _delete_user_by_github_id(gh_id)


@pytest.mark.asyncio
async def test_link_provider_rejects_id_already_owned_by_someone_else() -> None:
    """The actual conflict this project's linking design exists to
    prevent — never silently merge two accounts.
    """
    gh_id_a = _unique_id()
    gh_id_b = _unique_id()
    discord_id = _unique_id()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user_a = await login_or_create_user(
                    session, "github", Profile(provider_id=gh_id_a, email=None, display_name=None, avatar_url=None)
                )
                user_b = await login_or_create_user(
                    session, "github", Profile(provider_id=gh_id_b, email=None, display_name=None, avatar_url=None)
                )
        async with async_session_factory() as session:
            async with session.begin():
                await link_provider_to_current_user(
                    session,
                    current_user_id=user_a.id,
                    provider="discord",
                    profile=Profile(provider_id=discord_id, email=None, display_name=None, avatar_url=None),
                )
        with pytest.raises(AccountLinkConflict):
            async with async_session_factory() as session:
                async with session.begin():
                    await link_provider_to_current_user(
                        session,
                        current_user_id=user_b.id,
                        provider="discord",
                        profile=Profile(provider_id=discord_id, email=None, display_name=None, avatar_url=None),
                    )
    finally:
        await _delete_user_by_github_id(gh_id_a)
        await _delete_user_by_github_id(gh_id_b)


# ---------------------------------------------------------------------------
# HTTP layer — provider exchange mocked (no real OAuth app exists yet, #25)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_redirects_and_sets_state_cookie() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/github/authorize", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "github.com/login/oauth/authorize" in response.headers["location"]
    assert "afp_oauth_state" in response.cookies


@pytest.mark.asyncio
async def test_authorize_unknown_provider_404s() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/google/authorize", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_callback_rejects_state_that_doesnt_match_cookie() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("afp_oauth_state", "cookie-value")
        response = await client.get(
            "/api/v1/auth/github/callback", params={"code": "irrelevant", "state": "different-value"}
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_full_login_round_trip_with_mocked_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    gh_id = _unique_id()

    async def fake_exchange(config, code):  # noqa: ANN001, ARG001
        return "fake-access-token"

    async def fake_fetch_profile(config, token):  # noqa: ANN001, ARG001
        # normalize_profile() does str(raw["id"]) for github, so a plain
        # string id round-trips fine — no need for a real GitHub numeric id.
        return {"id": gh_id, "login": "tester", "email": None, "avatar_url": None}

    # routers.auth did `from services.oauth_providers import ...`, which
    # bound its own local name independent of the source module — patch
    # routers.auth's name, not oauth_providers', or the router still calls
    # the real (unreachable, no live OAuth app yet) function.
    monkeypatch.setattr("routers.auth.exchange_code_for_token", fake_exchange)
    monkeypatch.setattr("routers.auth.fetch_provider_profile", fake_fetch_profile)

    transport = ASGITransport(app=app)
    try:
        # https:// base_url, unlike the other tests in this file — the
        # state cookie is Secure (correctly, for the real deployment
        # behind Caddy's TLS termination), so httpx's cookie jar won't
        # attach it to a plain http:// request, same as a real browser
        # wouldn't. Confirmed this is a test-harness detail, not an app
        # bug, before "fixing" it this way rather than dropping Secure.
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            authorize_resp = await client.get("/api/v1/auth/github/authorize", follow_redirects=False)
            state = authorize_resp.cookies["afp_oauth_state"]

            callback_resp = await client.get(
                "/api/v1/auth/github/callback",
                params={"code": "irrelevant", "state": state},
            )
            assert callback_resp.status_code == 200, callback_resp.text
            body = callback_resp.json()
            assert body["role"] == "contributor"

            session_cookie = client.cookies.get("afp_session")
            assert session_cookie is not None
            assert verify_session_token(session_cookie) == body["id"]

            me_resp = await client.get("/api/v1/users/me")
            assert me_resp.status_code == 200
            assert me_resp.json()["id"] == body["id"]
    finally:
        await _delete_user_by_github_id(gh_id)


@pytest.mark.asyncio
async def test_users_me_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_users_me_reports_own_trust_score() -> None:
    """#43: GET /users/me exposes the caller's own trust_score, computed
    the same way #14/#27's admin listing computes it for anyone else.
    """
    from sqlalchemy import text as sql_text

    from core.security import SESSION_COOKIE_NAME, create_session_token

    gh_id = _unique_id()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await login_or_create_user(
                    session, "github", Profile(provider_id=gh_id, email=None, display_name=None, avatar_url=None)
                )
        user_id = user.id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
            fresh = await client.get("/api/v1/users/me")
            assert fresh.status_code == 200
            assert fresh.json()["approved_count"] == 0
            assert fresh.json()["rejected_count"] == 0
            assert fresh.json()["trust_score"] == 0

            # Seed one approved and one rejected contribution directly
            # (mirrors tests/test_admin.py's own _create_contribution
            # pattern) rather than exercising the full submit->approve
            # flow, which isn't what's under test here.
            async with async_session_factory() as session:
                async with session.begin():
                    series_id = (
                        await session.execute(sql_text("SELECT id FROM series LIMIT 1"))
                    ).scalar_one()
                    for status in ("approved", "rejected"):
                        citation_id = (
                            await session.execute(
                                sql_text(
                                    "INSERT INTO citations (url, description, submitted_by) "
                                    "VALUES ('https://example.com', '__test_43__citation', :uid) RETURNING id"
                                ),
                                {"uid": user_id},
                            )
                        ).scalar_one()
                        await session.execute(
                            sql_text(
                                """
                                INSERT INTO contributions
                                    (series_id, episode_number, proposed_status, citation_id,
                                     submitted_by, review_status, license_accepted)
                                VALUES (:sid, 999002, 'canon', :cid, :uid, :status, true)
                                """
                            ),
                            {"sid": series_id, "cid": citation_id, "uid": user_id, "status": status},
                        )

            updated = await client.get("/api/v1/users/me")
            assert updated.json()["approved_count"] == 1
            assert updated.json()["rejected_count"] == 1
            assert updated.json()["trust_score"] == 1 - (1 * 2)  # REJECTION_PENALTY = 2
    finally:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    sql_text("DELETE FROM contributions WHERE submitted_by = :uid"), {"uid": user_id}
                )
                await session.execute(
                    sql_text("DELETE FROM citations WHERE submitted_by = :uid"), {"uid": user_id}
                )
        await _delete_user_by_github_id(gh_id)


@pytest.mark.asyncio
async def test_delete_me_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/api/v1/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_me_removes_own_account_and_clears_session() -> None:
    """#29/#18: self-service deletion, no admin gate — deletes the caller's
    own row and clears the session cookie so the deleted account can't
    keep using it.

    Checks the Set-Cookie header directly rather than httpx's client-side
    cookie jar: a cookie seeded via `client.cookies.set(...)` (not received
    from a real Set-Cookie response) doesn't reconcile against a later
    deletion Set-Cookie in httpx's jar — confirmed as a test-harness quirk,
    not a server bug (the header itself is correct; any real browser
    clears it). What actually matters — a stale token becomes unusable —
    is checked below instead: the user row is gone, so get_current_user's
    lookup 401s on any later request with the old token, regardless of
    what any particular client does with the Set-Cookie header.
    """
    from core.security import SESSION_COOKIE_NAME, create_session_token

    gh_id = _unique_id()
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session, "github", Profile(provider_id=gh_id, email=None, display_name=None, avatar_url=None)
            )
    user_id = user.id
    stale_token = create_session_token(user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, stale_token)
        response = await client.delete("/api/v1/users/me")
        assert response.status_code == 204
        set_cookie = response.headers.get("set-cookie", "")
        assert SESSION_COOKIE_NAME in set_cookie
        assert "Max-Age=0" in set_cookie  # the server did tell the client to clear it

    async with async_session_factory() as session:
        row = (
            await session.execute(text("SELECT id FROM users WHERE id = :id"), {"id": user_id})
        ).first()
        assert row is None

    # The stale token is a validly-signed cookie for an id that no longer
    # exists — this is what actually makes it unusable post-deletion.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, stale_token)
        reused = await client.get("/api/v1/users/me")
        assert reused.status_code == 401


@pytest.mark.asyncio
async def test_delete_me_anonymizes_past_contributions_not_deletes_them() -> None:
    """The whole point of ON DELETE SET NULL (schema.sql) — a deleted
    user's past contributions stay in the audit trail, just no longer
    attributed to them.
    """
    from sqlalchemy import text as sql_text

    from core.security import SESSION_COOKIE_NAME, create_session_token

    gh_id = _unique_id()
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session, "github", Profile(provider_id=gh_id, email=None, display_name=None, avatar_url=None)
            )
    user_id = user.id

    series_id = None
    contribution_id = None
    try:
        async with async_session_factory() as session:
            async with session.begin():
                series_id = (
                    await session.execute(
                        sql_text(
                            "INSERT INTO series (title, provenance) VALUES "
                            "('__test_29__series', 'community') RETURNING id"
                        )
                    )
                ).scalar_one()
                citation_id = (
                    await session.execute(
                        sql_text(
                            "INSERT INTO citations (url, description, submitted_by) "
                            "VALUES ('https://example.com', '__test_29__citation', :uid) RETURNING id"
                        ),
                        {"uid": user_id},
                    )
                ).scalar_one()
                contribution_id = (
                    await session.execute(
                        sql_text(
                            """
                            INSERT INTO contributions
                                (series_id, episode_number, proposed_status, citation_id,
                                 submitted_by, review_status, license_accepted)
                            VALUES (:sid, 1, 'canon', :cid, :uid, 'pending', true)
                            RETURNING id
                            """
                        ),
                        {"sid": series_id, "cid": citation_id, "uid": user_id},
                    )
                ).scalar_one()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
            response = await client.delete("/api/v1/users/me")
            assert response.status_code == 204

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    sql_text("SELECT submitted_by FROM contributions WHERE id = :id"),
                    {"id": contribution_id},
                )
            ).one()
            assert row.submitted_by is None  # anonymized, not deleted
    finally:
        async with async_session_factory() as session:
            async with session.begin():
                if contribution_id is not None:
                    await session.execute(
                        text("DELETE FROM contributions WHERE id = :id"), {"id": contribution_id}
                    )
                if series_id is not None:
                    await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})


@pytest.mark.asyncio
async def test_settings_link_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/settings/link/discord", follow_redirects=False)
    assert response.status_code == 401
