# Local (email + password) authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add email+password signup/login as a second, first-class way to authenticate on AniFillerPedia, coexisting with the existing GitHub/Discord OAuth flow without replacing it.

**Architecture:** One new nullable column (`password_hash`) on the existing `users` table, following the exact layered pattern this codebase already uses for OAuth (`repositories/users.py` → `services/auth.py` → `routers/auth.py`), reusing the existing session-cookie mechanism verbatim. A new `/login` page becomes the primary entry point; the two existing OAuth links move there as a secondary option.

**Tech Stack:** FastAPI, raw SQL via SQLAlchemy `text()` (no ORM — this codebase never uses one), `argon2-cffi` for password hashing, Astro for the frontend page.

**Spec:** `docs/superpowers/specs/2026-09-04-local-auth-design.md`

## Global Constraints

- Passwords are **hashed** (argon2id), never encrypted — no reversible storage of any kind.
- `password_hash` is nullable and lives on the **existing** `users` table — never a separate table, never replacing the OAuth id columns.
- Email uniqueness is enforced **only** for rows with `password_hash IS NOT NULL` (a partial index) — existing OAuth-only rows must never be touched or constrained by this migration.
- No email verification, no password-reset flow, no CAPTCHA — all three explicitly deferred per the spec. Do not build any of them as part of this plan.
- Minimum password length: 8 characters. No other complexity rule.
- Rate limiting reuses `repositories/rate_limits.py`'s existing `count_recent`/`record` functions — no new rate-limit table or mechanism.
- Real Postgres in every test that touches the database — this codebase never mocks its own DB.
- Every migration is applied to production **before** its app-code PR merges (migrate-then-merge) — this repo has had real outages from getting that order backwards more than once.

---

## Task 1: Migration — `password_hash` column + partial unique index

**Files:**
- Create: `backend/migrations/021_add_local_auth.sql`
- Modify: `backend/schema.sql:38-70` (the `users` table definition)

**Interfaces:**
- Produces: `users.password_hash TEXT` (nullable), `users_email_unique_when_local` unique index — every later task in this plan reads/writes this column.

- [ ] **Step 1: Check the real next free migration number**

Run: `git fetch origin master --quiet && git show origin/master:backend/migrations/ 2>/dev/null; ls backend/migrations/ | sort -V | tail -3`

Expected: confirms `020_add_traffic_daily_rollups.sql` is still the latest — if a newer one exists on `origin/master` that isn't in your local checkout, pull first and renumber this migration to match (this exact collision class has hit this repo's parallel-agent batches before).

- [ ] **Step 2: Write the migration file**

```sql
-- #224 (implementation of the 2026-09-04 local-auth design spec): adds
-- email+password login as a second, first-class way to authenticate,
-- coexisting with the existing GitHub/Discord OAuth columns rather than
-- replacing them. Additive only — one nullable column, one partial
-- index, no existing row touched.
--
-- password_hash is argon2id (services/auth.py), never a reversible
-- encryption of any kind — hashing is one-way and cannot be undone even
-- if the database and any key were both compromised, which encryption
-- cannot guarantee.
ALTER TABLE users ADD COLUMN password_hash TEXT;

-- Only local (password-having) accounts require a unique email. This
-- must NOT constrain existing OAuth-only rows, which were never
-- guaranteed unique on email (it was profile metadata only, sourced
-- from whichever provider supplied it) and must never break.
CREATE UNIQUE INDEX users_email_unique_when_local
    ON users (email)
    WHERE password_hash IS NOT NULL;
```

- [ ] **Step 3: Update `schema.sql` to match**

In `backend/schema.sql`, find the `users` table's `email` column and its existing comment (`-- from whichever provider supplied it; never the login key`). Replace that comment with:

```sql
    email         TEXT,          -- from whichever provider supplied it for OAuth-only rows;
                                  -- for local (password-having) rows, this IS the login key
                                  -- (see users_email_unique_when_local below)
```

Then add `password_hash TEXT,` as a new column immediately after `email` in the `CREATE TABLE users (` block, and add the same `CREATE UNIQUE INDEX users_email_unique_when_local ...` statement from Step 2 directly after the `users` table's closing `);` (matching how every other migration's schema.sql mirror is placed immediately after the table it modifies — check `019_add_user_suspension.sql`'s own schema.sql diff for the exact placement convention if unsure).

- [ ] **Step 4: Apply to local test-pg**

Run: `podman start afp-test-pg || podman run -d --name afp-test-pg -p 127.0.0.1:55432:5432 -e POSTGRES_USER=anifillerpedia -e POSTGRES_PASSWORD=testpass -e POSTGRES_DB=anifillerpedia postgres:16-alpine`

Then apply every migration in order (including the new one):
```bash
for f in backend/migrations/*.sql; do
  psql -h 127.0.0.1 -p 55432 -U anifillerpedia -d anifillerpedia -f "$f"
done
```

Expected: no errors, `021_add_local_auth.sql` applies cleanly.

- [ ] **Step 5: Verify the index and column exist**

Run: `psql -h 127.0.0.1 -p 55432 -U anifillerpedia -d anifillerpedia -c '\d users'`

Expected: output includes `password_hash | text` and `"users_email_unique_when_local" UNIQUE, btree (email) WHERE password_hash IS NOT NULL`.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/021_add_local_auth.sql backend/schema.sql
git commit -m "Add password_hash column + partial unique email index for local auth"
```

---

## Task 2: Password hashing utility

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/core/security.py`
- Test: `backend/tests/test_local_auth.py` (new file)

**Interfaces:**
- Consumes: nothing new.
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool` — Task 5's service layer calls both.

- [ ] **Step 1: Pin the current stable argon2-cffi release**

Run: `pip index versions argon2-cffi 2>&1 | head -3`

Add the exact version returned to `backend/requirements.txt`, alphabetically placed to match the existing file's ordering (after `asyncpg`, before `email-validator` — check the current file's exact ordering first since it may not be strictly alphabetical, and match whatever convention is actually there).

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_local_auth.py
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
```

- [ ] **Step 2b: Run it to verify it fails**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: FAIL — `ImportError: cannot import name 'hash_password' from 'core.security'`.

- [ ] **Step 3: Implement in `core/security.py`**

Add near the existing `hash_api_key`/`generate_api_key` functions (same file, same "credential handling lives here" grouping):

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """argon2id, not sha256/bcrypt — unlike hash_api_key above (a
    high-entropy generated token, where a fast hash is correct and
    standard), a human-chosen password has low entropy and needs an
    adaptive, deliberately-slow hash to resist brute-forcing even after
    a full database leak. PasswordHasher() defaults to argon2id with
    reasonable time/memory cost parameters.
    """
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Never raises on a wrong password — VerifyMismatchError is the
    library's expected signal for "doesn't match," not an error state
    calling code needs to handle specially.
    """
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/core/security.py backend/tests/test_local_auth.py
git commit -m "Add argon2id password hashing utility"
```

---

## Task 3: Repository layer — create and look up local users

**Files:**
- Modify: `backend/repositories/users.py`
- Test: `backend/tests/test_local_auth.py`

**Interfaces:**
- Consumes: nothing new (raw SQL via `text()`, matching every other function in this file).
- Produces: `create_local_user(session, *, email: str, password_hash: str, display_name: str, role: str) -> Row`, `find_by_email_local(session, email: str) -> Row | None` — Task 5's service layer calls both.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_local_auth.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_local_user'`.

- [ ] **Step 3: Implement in `repositories/users.py`**

Add near the existing `create_user`/`find_by_provider_id` functions:

```python
async def create_local_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str,
    role: str,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO users (email, password_hash, display_name, role, last_login_at)
            VALUES (:email, :password_hash, :display_name, :role, now())
            RETURNING *
            """
        ),
        {
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name,
            "role": role,
        },
    )
    return result.one()


async def find_by_email_local(session: AsyncSession, email: str) -> Row | None:
    """Only ever matches a row with password_hash set — an OAuth-only
    row sharing this email (structurally possible, since OAuth emails
    were never unique) must never be treated as a local account."""
    result = await session.execute(
        text("SELECT * FROM users WHERE email = :email AND password_hash IS NOT NULL"),
        {"email": email},
    )
    return result.one_or_none()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/repositories/users.py backend/tests/test_local_auth.py
git commit -m "Add repository functions for local user creation and lookup"
```

---

## Task 4: Signup/login request schemas

**Files:**
- Modify: `backend/schemas/auth.py` (check whether this file exists first — `services/auth.py` exists but the schemas may currently live inline in `routers/auth.py` or a shared `schemas/` module; if `backend/schemas/auth.py` doesn't exist yet, create it following the same pattern as `backend/schemas/admin.py`)

**Interfaces:**
- Produces: `LocalSignupIn(email: EmailStr, password: str, display_name: str)`, `LocalLoginIn(email: EmailStr, password: str)` — Task 6's router imports both.

- [ ] **Step 1: Check whether `backend/schemas/auth.py` already exists**

Run: `ls backend/schemas/auth.py 2>&1; grep -rn "class.*BaseModel" backend/routers/auth.py backend/schemas/*.py 2>/dev/null | grep -i auth`

- [ ] **Step 2: Write the schemas**

If `backend/schemas/auth.py` doesn't exist, create it; if it does, add to it. Either way:

```python
from pydantic import BaseModel, EmailStr, Field


class LocalSignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class LocalLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
```

`email-validator` (which `EmailStr` requires) is already in `backend/requirements.txt` — no new dependency here.

- [ ] **Step 3: Verify it imports cleanly**

Run: `cd backend && python -c "from schemas.auth import LocalSignupIn, LocalLoginIn; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/schemas/auth.py
git commit -m "Add LocalSignupIn/LocalLoginIn request schemas"
```

---

## Task 5: Service layer — signup, login, and owner bootstrap by email

**Files:**
- Modify: `backend/core/config.py`
- Modify: `backend/services/auth.py`
- Test: `backend/tests/test_local_auth.py`

**Interfaces:**
- Consumes: `hash_password`/`verify_password` (Task 2), `create_local_user`/`find_by_email_local` (Task 3), `touch_last_login` (already exists in `repositories/users.py`, used by `login_or_create_user`).
- Produces: `signup_local_user(session, *, email: str, password: str, display_name: str) -> Row` (raises `EmailAlreadyRegistered` on conflict), `login_local_user(session, *, email: str, password: str) -> Row | None` (returns `None` on any failure — wrong email or wrong password, deliberately indistinguishable to the caller) — Task 6's router calls both.

- [ ] **Step 1: Add the settings field**

In `backend/core/config.py`, immediately after the existing `initial_admin_github_id: str = ""` line, add:

```python
    initial_admin_email: str = ""
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_local_auth.py`:

```python
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
async def test_login_local_user_succeeds_with_correct_password() -> None:
    email = _unique_email()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await signup_local_user(
                    session, email=email, password="correct password", display_name="Tester"
                )
        async with async_session_factory() as session:
            async with session.begin():
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
            async with session.begin():
                user = await login_local_user(session, email=email, password="wrong password")
            assert user is None
    finally:
        await _delete_user_by_email(email)


@pytest.mark.asyncio
async def test_login_local_user_fails_for_unknown_email() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_local_user(
                session, email=_unique_email(), password="anything"
            )
        assert user is None
```

Check `get_settings` in `backend/core/config.py` is actually `@lru_cache`-decorated (so `.cache_clear()` is valid) before writing this test — if it's not cached, drop the `cache_clear()` calls and just `monkeypatch.setenv` directly, since an uncached settings getter re-reads the env on every call.

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: FAIL — `ImportError: cannot import name 'signup_local_user'`.

- [ ] **Step 4: Implement in `services/auth.py`**

Add near the existing `_is_bootstrap_owner`/`login_or_create_user` functions:

```python
class EmailAlreadyRegistered(Exception):
    """Raised when a signup targets an email already registered as a
    local account. Never silently overwrite or merge — the caller turns
    this into a 409, matching this project's existing pattern for other
    uniqueness constraints (e.g. the one-pending-per-episode rule)."""


def _is_bootstrap_owner_email(email: str) -> bool:
    settings = get_settings()
    return bool(settings.initial_admin_email) and email == settings.initial_admin_email


async def signup_local_user(
    session: AsyncSession, *, email: str, password: str, display_name: str
) -> Row:
    existing = await find_by_email_local(session, email)
    if existing is not None:
        raise EmailAlreadyRegistered(f"{email} is already registered")

    role = "owner" if _is_bootstrap_owner_email(email) else "contributor"
    return await create_local_user(
        session,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )


async def login_local_user(session: AsyncSession, *, email: str, password: str) -> Row | None:
    """Returns None on ANY failure — unknown email or wrong password are
    deliberately indistinguishable to the caller, so a login-failure
    response never discloses whether an email is registered at all."""
    user = await find_by_email_local(session, email)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    await touch_last_login(session, user.id)
    return user
```

Add the two new imports this needs at the top of `services/auth.py`:
```python
from core.security import hash_password, verify_password
from repositories.users import create_local_user, find_by_email_local
```//adjust the existing `from repositories.users import ...` line instead of adding a second one if it already imports from that module.

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/core/config.py backend/services/auth.py backend/tests/test_local_auth.py
git commit -m "Add local signup/login service functions and email-based owner bootstrap"
```

---

## Task 6: Router endpoints — `POST /auth/local/signup`, `POST /auth/local/login`

**Files:**
- Modify: `backend/routers/auth.py`
- Modify: `docs/API.md`
- Test: `backend/tests/test_local_auth.py`

**Interfaces:**
- Consumes: `LocalSignupIn`/`LocalLoginIn` (Task 4), `signup_local_user`/`login_local_user`/`EmailAlreadyRegistered` (Task 5), `create_session_token`/`SESSION_COOKIE_NAME` (already imported in this file), `count_recent`/`record` from `repositories.rate_limits` (new import).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_local_auth.py`:

```python
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
async def test_login_endpoint_rate_limits_repeated_failed_attempts() -> None:
    """Mirrors this project's existing rate-limit test shape (see
    test_contributions.py's own anonymous-submission rate-limit test)
    rather than inventing a new pattern."""
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
```

Before writing the rate-limit test's exact expected attempt count, check `routers/contributions.py`'s existing rate-limit test for its own real threshold/window values and mirror that scale rather than inventing a number — adjust the `range(12)` above to whatever actually trips the limit you configure in Step 4 below.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: FAIL — 404s on both new routes (they don't exist yet).

- [ ] **Step 3: Add the imports**

At the top of `backend/routers/auth.py`, add:
```python
from repositories.rate_limits import count_recent, record
from schemas.auth import LocalLoginIn, LocalSignupIn
from services.auth import EmailAlreadyRegistered, login_local_user, signup_local_user
```

- [ ] **Step 4: Implement both endpoints**

Add to `backend/routers/auth.py`, near the existing `authorize`/`callback` routes:

```python
_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes
_LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 10
_SIGNUP_RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour
_SIGNUP_RATE_LIMIT_MAX_ATTEMPTS = 5


@router.post(
    "/auth/local/signup",
    responses={409: {"model": ErrorDetail, "description": "Email already registered"}},
)
async def local_signup(
    payload: LocalSignupIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Real email+password signup — coexists with OAuth login, does not
    replace it. No email verification in v1 (see the design spec's
    explicitly-deferred list) — the account is active immediately.
    """
    ip_identifier = f"ip:{request.client.host if request.client else 'unknown'}"
    async with session.begin():
        recent = await count_recent(
            session,
            scope="local_signup",
            identifier=ip_identifier,
            window_seconds=_SIGNUP_RATE_LIMIT_WINDOW_SECONDS,
        )
        if recent >= _SIGNUP_RATE_LIMIT_MAX_ATTEMPTS:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many signup attempts")
        await record(session, scope="local_signup", identifier=ip_identifier)
        try:
            user = await signup_local_user(
                session, email=payload.email, password=payload.password, display_name=payload.display_name
            )
        except EmailAlreadyRegistered as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.id),
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


@router.post(
    "/auth/local/login",
    responses={401: {"model": ErrorDetail, "description": "Invalid email or password"}},
)
async def local_login(
    payload: LocalLoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Keyed on email+IP together, not IP alone — this slows down
    # credential-stuffing against one targeted account without
    # collateral-blocking every other login attempt sharing that IP
    # (an office network, a VPN exit node, etc.), per the design spec.
    rate_identifier = f"login:{payload.email}:{request.client.host if request.client else 'unknown'}"
    async with session.begin():
        recent = await count_recent(
            session,
            scope="local_login",
            identifier=rate_identifier,
            window_seconds=_LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )
        if recent >= _LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many login attempts")
        await record(session, scope="local_login", identifier=rate_identifier)
        user = await login_local_user(session, email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.id),
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}
```

Add `Request` to the existing `fastapi` import line at the top of the file if it isn't already imported.

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && pytest tests/test_local_auth.py -v`
Expected: 18 passed. Then run the full suite: `pytest -v` — report the total pass count and confirm nothing else regressed.

- [ ] **Step 6: Update `docs/API.md`**

Add a subsection under the existing Authentication section documenting `POST /api/v1/auth/local/signup` and `POST /api/v1/auth/local/login` — request/response shapes, the 409/401/422/429 error cases, and a note that no email verification exists in v1 (matching how this doc already documents other known-limitation notes elsewhere).

- [ ] **Step 7: Commit**

```bash
git add backend/routers/auth.py backend/tests/test_local_auth.py docs/API.md
git commit -m "Add POST /auth/local/signup and /auth/local/login endpoints"
```

---

## Task 7: Frontend — new `/login` page

**Files:**
- Create: `frontend/src/pages/login.astro`

**Interfaces:**
- Consumes: `POST /api/v1/auth/local/signup`, `POST /api/v1/auth/local/login` (Task 6), the existing `LinkProviderButton.astro`-adjacent OAuth-link pattern from `Header.astro` (reuse the same `authorizeHref` construction, don't reinvent it).

- [ ] **Step 1: Check the existing form/page conventions to match**

Run: `cat frontend/src/pages/propose-series.astro | head -60` and `cat frontend/src/layouts/Layout.astro | head -30` — confirm the exact `Layout` props shape (`title`, `description`) and how an existing form page handles client-side submit (a plain inline `<script>` posting via `fetch`, matching this project's "no framework island" convention used everywhere else).

- [ ] **Step 2: Write the page**

```astro
---
// #224: local email+password login/signup, primary entry point per the
// 2026-09-04 design spec. The existing GitHub/Discord OAuth links stay
// fully functional below, in case #25's provisioning ever completes —
// nothing about that flow changes here.
import Layout from "../layouts/Layout.astro";

const baseUrl = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const next = Astro.url.searchParams.get("next") ?? "/";
const authorizeHref = (provider: "github" | "discord") =>
  `${baseUrl}/api/v1/auth/${provider}/authorize?next=${encodeURIComponent(next)}`;
---

<Layout title="Log in — AniFillerPedia" description="Log in or create an account to contribute to AniFillerPedia.">
  <h1 class="disp page-title">Log in</h1>

  <div class="auth-toggle">
    <button type="button" id="tab-login" class="tab-active" data-tab="login">Log in</button>
    <button type="button" id="tab-signup" data-tab="signup">Sign up</button>
  </div>

  <form id="login-form" data-mode="login">
    <label class="field">
      <span>Email</span>
      <input type="email" name="email" required autocomplete="email" />
    </label>
    <label class="field">
      <span>Password</span>
      <input type="password" name="password" required autocomplete="current-password" minlength="8" />
    </label>
    <label class="field" id="display-name-field" hidden>
      <span>Display name</span>
      <input type="text" name="display_name" autocomplete="nickname" />
    </label>
    <p class="error-note" id="form-error" hidden></p>
    <button type="submit" class="submit-btn">Log in</button>
  </form>

  <div class="oauth-secondary">
    <p class="oauth-label">Or continue with:</p>
    <a href={authorizeHref("github")}>GitHub</a>
    <a href={authorizeHref("discord")}>Discord</a>
  </div>
</Layout>

<script define:vars={{ next }}>
  const form = document.getElementById("login-form");
  const tabLogin = document.getElementById("tab-login");
  const tabSignup = document.getElementById("tab-signup");
  const displayNameField = document.getElementById("display-name-field");
  const errorNote = document.getElementById("form-error");

  function setMode(mode) {
    form.dataset.mode = mode;
    tabLogin.classList.toggle("tab-active", mode === "login");
    tabSignup.classList.toggle("tab-active", mode === "signup");
    displayNameField.hidden = mode !== "signup";
    form.querySelector('button[type="submit"]').textContent = mode === "signup" ? "Sign up" : "Log in";
    errorNote.hidden = true;
  }

  tabLogin.addEventListener("click", () => setMode("login"));
  tabSignup.addEventListener("click", () => setMode("signup"));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorNote.hidden = true;
    const mode = form.dataset.mode;
    const formData = new FormData(form);
    const path = mode === "signup" ? "/api/v1/auth/local/signup" : "/api/v1/auth/local/login";
    const body =
      mode === "signup"
        ? {
            email: formData.get("email"),
            password: formData.get("password"),
            display_name: formData.get("display_name"),
          }
        : { email: formData.get("email"), password: formData.get("password") };

    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });

    if (response.ok) {
      window.location.href = next;
      return;
    }

    if (response.status === 409) {
      errorNote.textContent = "That email is already registered — try logging in instead.";
    } else if (response.status === 401) {
      errorNote.textContent = "Incorrect email or password.";
    } else if (response.status === 429) {
      errorNote.textContent = "Too many attempts — please wait a few minutes and try again.";
    } else if (response.status === 422) {
      errorNote.textContent = "Please check your email and use a password of at least 8 characters.";
    } else {
      errorNote.textContent = "Something went wrong — please try again.";
    }
    errorNote.hidden = false;
  });
</script>

<style>
  .page-title {
    color: var(--color-heading);
    margin-bottom: 16px;
  }
  .auth-toggle {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
  }
  .auth-toggle button {
    font-family: var(--font-body);
    font-weight: 700;
    font-size: 13px;
    padding: 8px 16px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--color-border-card);
    background: var(--color-surface);
    color: var(--color-text-muted);
    cursor: pointer;
  }
  .auth-toggle button.tab-active {
    background: var(--color-accent);
    color: #fff;
    border-color: var(--color-accent);
  }
  form {
    display: flex;
    flex-direction: column;
    gap: 14px;
    max-width: 360px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 13px;
    font-weight: 700;
    color: var(--color-text);
  }
  .field input {
    padding: 10px 12px;
    border-radius: var(--radius-card);
    border: 1px solid var(--color-border-card);
    font-size: 14px;
  }
  .error-note {
    background: var(--color-dispute-bg);
    color: var(--color-dispute);
    border-radius: var(--radius-card);
    padding: 10px 12px;
    font-size: 13px;
    font-weight: 700;
  }
  .submit-btn {
    font-family: var(--font-display);
    font-weight: 700;
    padding: 10px 20px;
    border-radius: var(--radius-pill);
    border: none;
    background: var(--color-accent);
    color: #fff;
    cursor: pointer;
  }
  .oauth-secondary {
    margin-top: 28px;
    padding-top: 20px;
    border-top: 1px solid var(--color-border-card);
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .oauth-label {
    font-size: 12.5px;
    font-weight: 700;
    color: var(--color-text-muted);
    margin: 0;
  }
  .oauth-secondary a {
    font-size: 12.5px;
    font-weight: 700;
    color: var(--color-accent);
    text-decoration: none;
  }
</style>
```

Check the exact CSS custom property names (`--color-heading`, `--color-surface`, `--color-border-card`, `--color-dispute`/`--color-dispute-bg`, `--color-accent`, `--radius-pill`, `--radius-card`, `--font-display`, `--font-body`) against `frontend/src/styles/tokens.css` before finalizing — use whatever the real token names are if any of the above don't exist verbatim, rather than inventing new tokens.

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npx astro check && npx astro build`
Expected: 0 errors.

- [ ] **Step 4: Manual verification against a local dev server**

Run: `cd frontend && npm run dev` (with `PUBLIC_API_BASE_URL` pointed at a locally-running backend from Task 6), then fetch `http://localhost:4321/login` and confirm the page renders with both tabs, and that submitting the signup form against a real local backend actually creates an account and redirects.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/login.astro
git commit -m "Add /login page with local email+password auth as the primary option"
```

---

## Task 8: Rewire `Header.astro`'s login links to the new page

**Files:**
- Modify: `frontend/src/components/Header.astro:102-104`

**Interfaces:**
- Consumes: nothing new — this task only changes two `href` values.

- [ ] **Step 1: Read the current login-links block**

Run: `sed -n '95,110p' frontend/src/components/Header.astro`

- [ ] **Step 2: Replace the two direct-OAuth links with one link to `/login`**

Change:
```astro
        <span class="login-links">
          <a href={authorizeHref("github")}>{t("nav.logInGithub")}</a>
          <a href={authorizeHref("discord")}>{t("nav.logInDiscord")}</a>
        </span>
```
to:
```astro
        <span class="login-links">
          <a href={`/login?next=${next}`}>{t("nav.logIn")}</a>
        </span>
```

Check `frontend/src/i18n/ui.ts` for whether `nav.logIn` already exists as a key (unlikely — `nav.logInGithub`/`nav.logInDiscord` are the current keys); if not, add it to the English source-of-truth dictionary and all 4 other locale files with the same key, matching #106's own "every locale gets identical key coverage" convention. Use these exact translations (standard, well-established UI strings, not placeholders):

| Locale | Value |
|---|---|
| `en` | `Log in` |
| `es` | `Iniciar sesión` |
| `hi` | `लॉग इन करें` |
| `ja` | `ログイン` |
| `zh-cn` | `登录` |

- [ ] **Step 3: Verify it builds and check(s) pass**

Run: `cd frontend && npx astro check && npx astro build`
Expected: 0 errors. Also run whatever i18n key-coverage test this project already has (check `frontend/src/i18n/` for an existing `i18n.test.ts`-style check) to confirm the new key exists in every locale.

- [ ] **Step 4: Manual verification**

Run a local dev server, load the homepage while logged out, confirm the header now shows one "Log in" link, and clicking it lands on `/login` with the `next` param correctly carried through (matching the existing `next`-preservation behavior `Header.astro`'s own file-header comment already describes for the old OAuth links).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Header.astro frontend/src/i18n/ui.ts
git commit -m "Rewire header login link to the new /login page"
```

---

## Final verification (whole plan)

- [ ] Full backend test suite passes: `cd backend && pytest -v` — report the exact pass count and compare against the pre-plan baseline to confirm nothing regressed.
- [ ] `astro check` and `astro build` both clean.
- [ ] Migration applied to production **before** merging the app-code PR (migrate-then-merge) — confirm via `\d users` on the live droplet showing `password_hash` and `users_email_unique_when_local`.
- [ ] Live end-to-end check on production after deploy: sign up a real throwaway test account via the live `/login` page, confirm the session cookie is set and `GET /api/v1/users/me` reflects the new account, then delete that test row directly (this is a real production write — clean up after verifying, same as this project's other live-data verification passes).
- [ ] Confirm `INITIAL_ADMIN_EMAIL` is documented in `CLAUDE.local.md`'s external-account/secrets section (gitignored, not part of this PR's diff) — a manual follow-up note for whichever session finishes this plan, not a git-tracked step.
