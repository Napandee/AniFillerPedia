from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # asyncpg driver — note the +asyncpg, not psycopg2 (AniDex uses sync
    # psycopg2; this project's stack is async SQLAlchemy throughout).
    database_url: str
    environment: str = "development"

    # Outbox worker (#9) — how often it polls when there's nothing to do.
    # Not a message broker's push latency; a few seconds is fine for
    # moderator notifications / cache purges, per CLAUDE.md Architecture.
    worker_poll_interval_seconds: int = 5
    worker_batch_size: int = 10

    # Auth (#8) — GitHub + Discord OAuth. Real values don't exist yet
    # (#25, still open) — routes work structurally without them, live
    # provider round-trips can't be verified until then.
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    discord_oauth_client_id: str = ""
    discord_oauth_client_secret: str = ""
    initial_admin_github_id: str = ""

    # Signs session cookies and the OAuth `state` param (CSRF protection +
    # carrying "this is a /settings/link attempt for user N" safely across
    # the redirect to the provider and back). Session model is a signed,
    # stateless cookie (itsdangerous), not a server-side sessions table —
    # deliberate: avoids a schema change while three agents share
    # schema.sql in parallel today (#7, #4 also mid-flight). Trade-off
    # worth knowing: logout can't force-invalidate a still-valid signed
    # cookie server-side, only clear it client-side. Acceptable for v1,
    # revisit if that ever actually matters.
    session_secret_key: str = "dev-insecure-change-me"
    session_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # Public origin this API is served at — needed to build OAuth redirect
    # URIs (must exactly match what's registered with each provider).
    public_base_url: str = "http://localhost:8000"

    # Cloudflare Turnstile (#12/#20) — anonymous submission endpoint only.
    # Empty until a real site is provisioned; see services/turnstile.py's
    # docstring for what happens while it's unset.
    turnstile_secret_key: str = ""

    # Outbox consumers (#15). Neither token is set yet — both handlers are
    # structurally correct and were verified against the real Telegram Bot
    # API / Cloudflare purge_cache API shapes, but can't be live-verified
    # end-to-end from inside the app until these are provisioned (same
    # category of gap as OAuth/Turnstile — see CLAUDE.local.md's
    # consolidated external-account checklist).
    telegram_bot_token: str = ""
    # Chat ID for the existing brantholm_github_bot, per global
    # ~/.claude/CLAUDE.md — already public knowledge, safe to default here.
    # The bot token itself is the actual secret and stays empty by default.
    telegram_chat_id: str = "8528154154"

    cloudflare_api_token: str = ""
    # anifillerpedia.wiki's real zone ID, confirmed live 2026-08-21 (not
    # sensitive — Cloudflare zone IDs aren't secrets, the API token is).
    cloudflare_zone_id: str = "090a6d6b91e55f92740f23bad2c11de6"
    public_site_base_url: str = "https://anifillerpedia.wiki"


@lru_cache
def get_settings() -> Settings:
    return Settings()
