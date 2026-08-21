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
async def test_settings_link_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/settings/link/discord", follow_redirects=False)
    assert response.status_code == 401
