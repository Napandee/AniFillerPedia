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
