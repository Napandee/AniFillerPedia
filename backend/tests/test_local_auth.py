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
