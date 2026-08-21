"""Business logic for login/link — the rules CLAUDE.md's Guardrails care
about live here, not in the router: explicit-only linking, admin
bootstrap via env var rather than first-user-wins.
"""

from dataclasses import dataclass

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from repositories.users import create_user, find_by_provider_id, link_provider, touch_last_login


class AccountLinkConflict(Exception):
    """Raised when a /settings/link/{provider} attempt targets a
    provider_id already linked to a DIFFERENT user. Never silently merge
    or steal accounts.
    """


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
