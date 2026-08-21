"""Cloudflare Turnstile verification for the anonymous contribution
submission endpoint (CLAUDE.md, decided 2026-08-21, issue #20).

Structurally ready, NOT live-verified: no Turnstile site/secret key has
been provisioned yet (same category of gap as #8's OAuth apps before #25 —
the code is real, the external service account isn't set up). While
`settings.turnstile_secret_key` is empty, verify() short-circuits to
allowed=True so the submission endpoint isn't hard-blocked before a real
key exists — this must be revisited once Turnstile is actually configured,
otherwise the check is silently a no-op forever.
"""

import httpx

from core.config import get_settings

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify(token: str | None) -> bool:
    settings = get_settings()
    if not settings.turnstile_secret_key:
        return True  # not configured yet — see module docstring
    if not token:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            VERIFY_URL, data={"secret": settings.turnstile_secret_key, "response": token}
        )
    return bool(response.json().get("success"))
