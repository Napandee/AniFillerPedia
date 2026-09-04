"""Tests for local (email+password) authentication — #224, implementing
docs/superpowers/specs/2026-09-04-local-auth-design.md.

Real Postgres throughout, per this project's standing convention —
nothing here mocks the database.
"""

import uuid

import pytest

from core.security import hash_password, verify_password


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@example.com"


def test_hash_password_produces_a_verifiable_hash() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password entirely", hashed)


def test_hash_password_is_salted_differently_each_time() -> None:
    """Two hashes of the same password must differ (argon2 embeds a
    random salt per-hash) — this is what stops a rainbow-table attack
    against the whole users table at once."""
    first = hash_password("same password")
    second = hash_password("same password")
    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_verify_password_handles_none_password_hash() -> None:
    """OAuth-only accounts have NULL password_hash in the database.
    verify_password must handle this gracefully, not raise."""
    assert not verify_password("any password", None)


def test_verify_password_handles_empty_string_password_hash() -> None:
    """Corrupted or invalid password_hash values must return False,
    never raise, so login can safely attempt password verification
    even when the hash is garbage."""
    assert not verify_password("any password", "")


def test_verify_password_handles_malformed_hash() -> None:
    """Garbage strings, truncated hashes, etc. must return False."""
    assert not verify_password("password", "not-a-hash")
    assert not verify_password("password", "garbage-string")
    # Truncated real hash (missing closing $-delimited segment)
    assert not verify_password("password", "$argon2id$v=19$m=19456,t=2,p=1")


from core.db import async_session_factory
from repositories.users import create_local_user, find_by_email_local
from sqlalchemy import text


async def _delete_user_by_email(email: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})


@pytest.mark.asyncio
async def test_create_local_user_persists_a_real_row() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await create_local_user(
                    session,
                    email=email,
                    password_hash=hash_password("a real password"),
                    display_name="Local Tester",
                    role="contributor",
                )
            assert user.email == email
            assert user.display_name == "Local Tester"
            assert user.role == "contributor"
            assert user.password_hash is not None
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_find_by_email_local_ignores_oauth_only_rows() -> None:
    """An OAuth-only row sharing the same email (a real, structurally
    possible case since OAuth emails were never unique) must never be
    returned by a local-account lookup — that would let a password-login
    attempt silently authenticate as someone else's OAuth-linked account."""
    email = _unique_email()
    from repositories.users import create_user

    try:
        async with async_session_factory() as session:
            async with session.begin():
                await create_user(
                    session,
                    provider="github",
                    provider_id=f"gh-{uuid.uuid4().hex[:12]}",
                    email=email,
                    display_name="OAuth Only",
                    avatar_url=None,
                    role="contributor",
                )
        async with async_session_factory() as session:
            found = await find_by_email_local(session, email)
            assert found is None
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_find_by_email_local_finds_a_real_local_account() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await create_local_user(
                    session,
                    email=email,
                    password_hash=hash_password("a real password"),
                    display_name="Local Tester",
                    role="contributor",
                )
        async with async_session_factory() as session:
            found = await find_by_email_local(session, email)
            assert found is not None
            assert found.email == email
    finally:
        await _delete_user_by_email(email)


from services.auth import EmailAlreadyRegistered, login_local_user, signup_local_user


@pytest.mark.asyncio
async def test_signup_local_user_creates_a_contributor_by_default() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await signup_local_user(
                    session, email=email, password="a real password", display_name="New Signup"
                )
            assert user.role == "contributor"
            assert user.email == email
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_local_user_rejects_duplicate_email() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await signup_local_user(
                    session, email=email, password="first password", display_name="First"
                )
        async with async_session_factory() as session:
            async with session.begin():
                with pytest.raises(EmailAlreadyRegistered):
                    await signup_local_user(
                        session, email=email, password="second password", display_name="Second"
                    )
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_local_user_matching_initial_admin_email_becomes_owner(monkeypatch) -> None:
    email = _unique_email()
    from core.config import get_settings
    from repositories.users import owner_exists

    async with async_session_factory() as session:
        if await owner_exists(session):
            pytest.skip("an owner row already exists in this database — the "
                        "email bootstrap is deliberately one-shot (see the "
                        "guard test below), so this case can't be exercised")

    get_settings.cache_clear()
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", email)
    get_settings.cache_clear()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                user = await signup_local_user(
                    session, email=email, password="owner password", display_name="Owner"
                )
            assert user.role == "owner"
    finally:
        get_settings.cache_clear()
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_matching_initial_admin_email_is_ignored_once_an_owner_exists(
    monkeypatch,
) -> None:
    """Final-review fix (C2): a signup email is attacker-controlled free
    text, unlike the provider-attested GitHub id the OAuth bootstrap keys
    on. Without this guard, anyone who guessed (or simply raced to) the
    configured address would mint themselves 'owner'. The bootstrap must
    be genuinely one-shot: once an owner exists, a matching email is
    treated exactly as if it hadn't matched at all."""
    owner_email = _unique_email()
    attacker_email = _unique_email()
    from core.config import get_settings

    try:
        # A real existing owner, whatever their origin.
        async with async_session_factory() as session:
            async with session.begin():
                await create_local_user(
                    session,
                    email=owner_email,
                    password_hash=hash_password("the real owner"),
                    display_name="Existing Owner",
                    role="owner",
                )

        get_settings.cache_clear()
        monkeypatch.setenv("INITIAL_ADMIN_EMAIL", attacker_email)
        get_settings.cache_clear()

        async with async_session_factory() as session:
            async with session.begin():
                user = await signup_local_user(
                    session,
                    email=attacker_email,
                    password="not the owner",
                    display_name="Latecomer",
                )
            assert user.role == "contributor"
    finally:
        get_settings.cache_clear()
        await _delete_user_by_email(owner_email)
        await _delete_user_by_email(attacker_email)


@pytest.mark.asyncio
async def test_local_auth_email_is_case_insensitive() -> None:
    """Final-review fix (I2): Pydantic's EmailStr lowercases only the
    domain half, so without service-layer normalization `Foo@x.com` and
    `foo@x.com` would be two unrelated accounts — and with no password
    reset in v1, a user who signed up with a stray capital would have no
    way back into their own account."""
    email = _unique_email()
    local_part, _, domain = email.partition("@")
    # Uppercased local part (the half EmailStr leaves alone) plus stray
    # surrounding whitespace — both must normalize away.
    mixed_case = f"  {local_part.upper()}@{domain}  "
    try:
        async with async_session_factory() as session:
            async with session.begin():
                created = await signup_local_user(
                    session, email=mixed_case, password="a real password", display_name="Mixed"
                )
            # Stored canonically, not as typed.
            assert created.email == email

        async with async_session_factory() as session:
            user = await login_local_user(session, email=email, password="a real password")
            assert user is not None
            assert user.id == created.id

        async with async_session_factory() as session:
            user = await login_local_user(
                session, email=mixed_case, password="a real password"
            )
            assert user is not None
            assert user.id == created.id
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_local_user_succeeds_with_correct_password() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await signup_local_user(
                    session, email=email, password="correct password", display_name="Tester"
                )
        # No `session.begin()` wrapper: login_local_user deliberately owns
        # its own short transactions so the argon2 verify never runs with
        # a pooled connection held open (final-review fix I3).
        async with async_session_factory() as session:
            user = await login_local_user(session, email=email, password="correct password")
            assert user is not None
            assert user.email == email
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_local_user_fails_with_wrong_password() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await signup_local_user(
                    session, email=email, password="correct password", display_name="Tester"
                )
        async with async_session_factory() as session:
            user = await login_local_user(session, email=email, password="wrong password")
            assert user is None
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_local_user_fails_for_unknown_email() -> None:
    async with async_session_factory() as session:
        user = await login_local_user(session, email=_unique_email(), password="anything")
        assert user is None


from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_signup_endpoint_creates_account_and_sets_session_cookie() -> None:
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "a real password", "display_name": "New User"},
            )
        assert response.status_code == 200
        assert "afp_session" in response.cookies
        body = response.json()
        assert body["email"] == email
        assert body["role"] == "contributor"
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_endpoint_rejects_duplicate_email_with_409() -> None:
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "first password", "display_name": "First"},
            )
            response = await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "second password", "display_name": "Second"},
            )
        assert response.status_code == 409
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_endpoint_rejects_short_password_with_422() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/local/signup",
            json={"email": _unique_email(), "password": "short", "display_name": "Tester"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_endpoint_succeeds_and_sets_session_cookie() -> None:
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "correct password", "display_name": "Tester"},
            )
            response = await client.post(
                "/api/v1/auth/local/login",
                json={"email": email, "password": "correct password"},
            )
        assert response.status_code == 200
        assert "afp_session" in response.cookies
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_endpoint_rejects_wrong_password_with_401() -> None:
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "correct password", "display_name": "Tester"},
            )
            response = await client.post(
                "/api/v1/auth/local/login",
                json={"email": email, "password": "wrong password"},
            )
        assert response.status_code == 401
        assert "afp_session" not in response.cookies
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_endpoint_rate_limits_repeated_duplicate_email_attempts() -> None:
    """#221 fix-round-1: a duplicate-email signup attempt must still count
    against the signup rate limit, not just a successful one — otherwise
    an attacker can probe unlimited duplicate emails "for free" since
    each probe returns a clean 409 without ever touching the limit.
    Threshold is 5 attempts/3600s (_SIGNUP_RATE_LIMIT_MAX_ATTEMPTS in
    routers/auth.py): 1 real signup + up to 5 duplicate-email probes
    should trip 429 well within that budget."""
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "correct password", "display_name": "Tester"},
            )
            assert first.status_code == 200
            responses = []
            for _ in range(6):
                responses.append(
                    await client.post(
                        "/api/v1/auth/local/signup",
                        json={"email": email, "password": "some other password", "display_name": "Tester"},
                    )
                )
        assert all(r.status_code in (409, 429) for r in responses)
        assert any(r.status_code == 429 for r in responses)
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_endpoint_rate_limits_repeated_failed_attempts() -> None:
    """Mirrors this project's existing rate-limit test shape
    (test_rate_limits_and_validation.py's #139 anonymous-submission
    rate-limit tests) rather than inventing a new pattern. Threshold here
    is 10 attempts/300s (_LOGIN_RATE_LIMIT_MAX_ATTEMPTS in routers/auth.py)
    — range(12) trips it on the 11th attempt, same scale as this
    codebase's existing rate-limit thresholds (#139's 20/hour,
    #84/#141's 10-count seeded checks)."""
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "correct password", "display_name": "Tester"},
            )
            responses = []
            for _ in range(12):
                responses.append(
                    await client.post(
                        "/api/v1/auth/local/login",
                        json={"email": email, "password": "wrong password"},
                    )
                )
        assert any(r.status_code == 429 for r in responses)
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_rate_limit_shares_one_bucket_across_email_case() -> None:
    """Final-review re-review finding: normalize_email() made login
    case-insensitive (services/auth.py), but the rate-limit identifier in
    routers/auth.py was built from the raw, un-normalized payload.email —
    so varying case on each attempt bought a fresh bucket every time,
    turning the 10-attempts/300s limiter into an effectively unbounded
    one for the exact account it's meant to protect. Proves attempts
    against differently-cased spellings of the same email all land in
    one bucket and still trip 429."""
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "correct password", "display_name": "Tester"},
            )
            assert first.status_code == 200
            responses = []
            for i in range(12):
                varied_email = email.upper() if i % 2 == 0 else email
                responses.append(
                    await client.post(
                        "/api/v1/auth/local/login",
                        json={"email": varied_email, "password": "wrong password"},
                    )
                )
        assert any(r.status_code == 429 for r in responses)
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_session_cookie_authenticates_against_users_me() -> None:
    """Final-review fix (I6): the whole point of local auth is that its
    session cookie is the SAME session the rest of the API already
    accepts. Every other test here stops at "a cookie was set" — this one
    actually spends it on an existing authenticated endpoint and checks
    the identity that comes back."""
    email = _unique_email()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            signup = await client.post(
                "/api/v1/auth/local/signup",
                json={"email": email, "password": "a real password", "display_name": "Chain Tester"},
            )
            assert signup.status_code == 200
            token = signup.cookies["afp_session"]

            # Sent explicitly rather than relying on the client's cookie
            # jar — the cookie is Secure, which a jar may well refuse to
            # replay over this http:// test base_url, and that would make
            # the assertion below pass or fail for the wrong reason.
            me = await client.get(
                "/api/v1/users/me", headers={"Cookie": f"afp_session={token}"}
            )
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == email
        assert body["id"] == signup.json()["id"]
        assert body["role"] == "contributor"
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_two_oauth_only_rows_may_share_one_email() -> None:
    """The `users_email_unique_when_local` partial index (migration 021)
    must constrain LOCAL accounts only. OAuth emails were never unique —
    two providers can legitimately report the same address for what the
    provider side considers separate identities — so a blanket UNIQUE on
    users.email would have broken existing OAuth signups. The existing
    coverage only proves one such row is ignored by a local lookup; this
    proves two of them can actually coexist."""
    email = _unique_email()
    from repositories.users import create_user

    try:
        async with async_session_factory() as session:
            async with session.begin():
                first = await create_user(
                    session,
                    provider="github",
                    provider_id=f"gh-{uuid.uuid4().hex[:12]}",
                    email=email,
                    display_name="OAuth One",
                    avatar_url=None,
                    role="contributor",
                )
                second = await create_user(
                    session,
                    provider="discord",
                    provider_id=f"dc-{uuid.uuid4().hex[:12]}",
                    email=email,
                    display_name="OAuth Two",
                    avatar_url=None,
                    role="contributor",
                )
        assert first.id != second.id
        assert first.email == second.email == email

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT count(*) FROM users "
                    "WHERE email = :email AND password_hash IS NULL"
                ),
                {"email": email},
            )
            assert result.scalar() == 2
            # …and neither is reachable as a local account.
            assert await find_by_email_local(session, email) is None
    finally:
        await _delete_user_by_email(email)
