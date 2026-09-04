"""Business logic for login/link — the rules CLAUDE.md's Guardrails care
about live here, not in the router: explicit-only linking, admin
bootstrap via env var rather than first-user-wins.
"""

import secrets
from dataclasses import dataclass

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from core.config import get_settings
from core.security import hash_password, verify_password
from repositories.users import (
    create_local_user,
    create_user,
    find_by_email_local,
    find_by_provider_id,
    link_provider,
    owner_exists,
    touch_last_login,
)


class AccountLinkConflict(Exception):
    """Raised when a /settings/link/{provider} attempt targets a
    provider_id already linked to a DIFFERENT user. Never silently merge
    or steal accounts.
    """


class EmailAlreadyRegistered(Exception):
    """Raised when a signup targets an email already registered as a
    local account. Never silently overwrite or merge — the caller turns
    this into a 409, matching this project's existing pattern for other
    uniqueness constraints (e.g. the one-pending-per-episode rule)."""


@dataclass
class Profile:
    provider_id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None


def _is_bootstrap_owner(provider: str, provider_id: str) -> bool:
    settings = get_settings()
    return (
        provider == "github"
        and bool(settings.initial_admin_github_id)
        and provider_id == settings.initial_admin_github_id
    )


async def login_or_create_user(
    session: AsyncSession, provider: str, profile: Profile
) -> Row:
    """Ordinary login flow (not linking): find an existing account by this
    provider's id, or create one. Never touches any OTHER user's row —
    that's exactly the auto-link-by-email behavior this project's
    Guardrails forbid.
    """
    existing = await find_by_provider_id(session, provider, profile.provider_id)
    if existing is not None:
        await touch_last_login(session, existing.id)
        return existing

    # 'owner', not 'admin' — the bootstrap identity is the distinct top
    # tier decided 2026-08-21 (CLAUDE.md), never assignable any other way.
    role = "owner" if _is_bootstrap_owner(provider, profile.provider_id) else "contributor"
    return await create_user(
        session,
        provider=provider,
        provider_id=profile.provider_id,
        email=profile.email,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        role=role,
    )


def normalize_email(email: str) -> str:
    """The single normalization point for every local-auth email.

    Pydantic's EmailStr only lowercases the DOMAIN half, so without this
    `Foo@x.com` and `foo@x.com` would be two different local accounts with
    no way back (v1 has no password reset). Applied here at the service
    boundary — deliberately not scattered across the router or repository
    — so signup, login and the bootstrap-owner comparison all agree on
    exactly one canonical form.
    """
    return email.strip().lower()


_dummy_password_hash_cache: str | None = None


def _verify_against_dummy_hash(password: str) -> None:
    """Timing-attack mitigation for login_local_user (see its comment).

    Computed lazily rather than hard-coded so the cost parameters always
    match whatever hash_password() currently produces — a stale literal
    with different argon2 params would defeat the whole point by taking a
    measurably different amount of time from a real verify.
    """
    global _dummy_password_hash_cache
    if _dummy_password_hash_cache is None:
        _dummy_password_hash_cache = hash_password(secrets.token_urlsafe(32))
    verify_password(password, _dummy_password_hash_cache)


async def _is_bootstrap_owner_email(session: AsyncSession, email: str) -> bool:
    """Email-keyed counterpart to _is_bootstrap_owner, with one extra
    guard the OAuth path doesn't need: a signup email is attacker-
    controlled free text, whereas a GitHub provider_id is provider-
    attested (you must actually control that account to present it). So
    a bare string match is NOT sufficient here — whoever signs up first
    with the configured address would otherwise mint themselves 'owner'.
    Only fires while no owner row exists at all, making it a genuine
    one-shot bootstrap rather than a standing privilege grant.
    """
    settings = get_settings()
    if not settings.initial_admin_email:
        return False
    if email != normalize_email(settings.initial_admin_email):
        return False
    return not await owner_exists(session)


async def signup_local_user(
    session: AsyncSession, *, email: str, password: str, display_name: str
) -> Row:
    email = normalize_email(email)
    existing = await find_by_email_local(session, email)
    if existing is not None:
        raise EmailAlreadyRegistered(f"{email} is already registered")

    # 'owner', not 'admin' — same bootstrap-identity rule as the OAuth path
    # above (_is_bootstrap_owner), just keyed by email instead of a GitHub
    # provider_id, since a local account has no provider_id at all.
    role = "owner" if await _is_bootstrap_owner_email(session, email) else "contributor"
    # argon2 is deliberately slow (~50-100ms of real CPU); running it
    # inline would block the whole event loop for that long on every
    # signup, so it goes to a worker thread.
    password_hash = await run_in_threadpool(hash_password, password)
    return await create_local_user(
        session,
        email=email,
        password_hash=password_hash,
        display_name=display_name,
        role=role,
    )


async def login_local_user(session: AsyncSession, *, email: str, password: str) -> Row | None:
    """Returns None on ANY failure — unknown email or wrong password are
    deliberately indistinguishable to the caller, so a login-failure
    response never discloses whether an email is registered at all.

    Call this OUTSIDE any caller-owned `session.begin()` block: it manages
    its own short transactions on purpose, so the argon2 verify below
    never runs while a pooled DB connection is held open.
    """
    email = normalize_email(email)
    user = await find_by_email_local(session, email)
    # The lookup above is read-only, so ending its implicitly-begun
    # transaction here discards nothing — it just hands the connection
    # back to the pool before the ~50-100ms verify.
    if session.in_transaction():
        await session.rollback()

    if user is None:
        # Timing-attack mitigation: returning here immediately would make
        # an unregistered email measurably faster to reject than a
        # registered one with a wrong password, disclosing exactly what
        # this function's contract (and docs/API.md) promise it never
        # discloses. Burn a comparable argon2 verify against a dummy hash
        # instead. Do not "simplify" this away.
        await run_in_threadpool(_verify_against_dummy_hash, password)
        return None
    if not await run_in_threadpool(verify_password, password, user.password_hash):
        return None
    async with session.begin():
        await touch_last_login(session, user.id)
    return user


async def link_provider_to_current_user(
    session: AsyncSession, *, current_user_id: int, provider: str, profile: Profile
) -> None:
    """/settings/link/{provider} — the ONLY path that attaches a new
    provider to an existing account. Rejects outright if that provider_id
    is already linked to someone else; never merges accounts.
    """
    existing = await find_by_provider_id(session, provider, profile.provider_id)
    if existing is not None and existing.id != current_user_id:
        raise AccountLinkConflict(
            f"{provider} account is already linked to a different user"
        )
    if existing is not None and existing.id == current_user_id:
        return  # already linked to this same user — no-op, not an error
    await link_provider(
        session, user_id=current_user_id, provider=provider, provider_id=profile.provider_id
    )
