"""Provider configs + the generic OAuth2 authorization-code exchange.
GitHub and Discord only (#8) — Google is #24's job, added the same way
once it lands, not a redesign.

Hand-rolled rather than FastAPI Users' OAuth integration: FastAPI Users'
default OAuth flow auto-associates accounts by email match across
providers, which is exactly what CLAUDE.md's Guardrails forbid (explicit-
only linking, never automatic) — fighting that default was more complex
than this ~150-line module. Its SQLAlchemy adapter also assumes a
UUID-id/is_active/is_superuser/hashed_password shape that doesn't match
this project's actual `users` table.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from core.config import get_settings


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    client_id: str
    client_secret: str


def get_provider_config(provider: str) -> ProviderConfig:
    settings = get_settings()
    if provider == "github":
        return ProviderConfig(
            name="github",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            scope="read:user user:email",
            client_id=settings.github_oauth_client_id,
            client_secret=settings.github_oauth_client_secret,
        )
    if provider == "discord":
        return ProviderConfig(
            name="discord",
            authorize_url="https://discord.com/api/oauth2/authorize",
            token_url="https://discord.com/api/oauth2/token",
            userinfo_url="https://discord.com/api/users/@me",
            scope="identify email",
            client_id=settings.discord_oauth_client_id,
            client_secret=settings.discord_oauth_client_secret,
        )
    raise ValueError(f"unknown provider: {provider}")


def redirect_uri_for(provider: str) -> str:
    settings = get_settings()
    return f"{settings.public_base_url}/api/v1/auth/{provider}/callback"


async def exchange_code_for_token(provider_config: ProviderConfig, code: str) -> str:
    """Returns the access token. Raises httpx.HTTPStatusError on failure."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            provider_config.token_url,
            data={
                "client_id": provider_config.client_id,
                "client_secret": provider_config.client_secret,
                "code": code,
                "redirect_uri": redirect_uri_for(provider_config.name),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        body = response.json()
        if "access_token" not in body:
            raise ValueError(f"no access_token in {provider_config.name} response: {body}")
        return body["access_token"]


async def fetch_provider_profile(
    provider_config: ProviderConfig, access_token: str
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            provider_config.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def normalize_profile(provider: str, raw: dict[str, Any]) -> dict[str, str | None]:
    """Provider-specific field names -> the shape services/auth.py works
    with everywhere else: provider_id (str), email, display_name, avatar_url.
    """
    if provider == "github":
        return {
            "provider_id": str(raw["id"]),
            "email": raw.get("email"),
            "display_name": raw.get("login"),
            "avatar_url": raw.get("avatar_url"),
        }
    if provider == "discord":
        avatar_hash = raw.get("avatar")
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{raw['id']}/{avatar_hash}.png"
            if avatar_hash
            else None
        )
        return {
            "provider_id": str(raw["id"]),
            "email": raw.get("email"),
            "display_name": raw.get("username"),
            "avatar_url": avatar_url,
        }
    raise ValueError(f"unknown provider: {provider}")
