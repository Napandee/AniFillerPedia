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

    # AniList episode/air-date sync (#49) — a second, independently-paced
    # loop in the same worker container. Daily by default: this data only
    # needs to notice a newly-aired episode for a still-RELEASING show, not
    # react within seconds like the outbox poller above.
    episode_schedule_sync_interval_seconds: int = 60 * 60 * 24

    # #175 — third, independently-paced worker loop: a weekly, lightweight
    # re-check of series already marked anilist_status = 'FINISHED' (which
    # the daily sync above otherwise stops re-fetching forever). Weekly,
    # not daily: a FINISHED show resuming from hiatus is a rare event, and
    # the whole point of this loop is to be cheap since it's expected to
    # almost always come back unchanged.
    finished_series_drift_check_interval_seconds: int = 60 * 60 * 24 * 7

    # Auth — GitHub + Discord OAuth (#8) AND local email+password
    # (#224). The OAuth credentials' real values don't exist yet (#25,
    # still open) — those routes work structurally without them, but live
    # provider round-trips can't be verified until then; local auth needs
    # no external provisioning at all.
    #
    # The two bootstrap settings below are the same idea keyed two ways:
    # initial_admin_github_id matches an OAuth login's provider-attested
    # GitHub id, initial_admin_email matches a local signup's address.
    # Because a signup email is attacker-controlled free text, the email
    # path additionally only grants 'owner' while no owner row exists yet
    # (services/auth.py::_is_bootstrap_owner_email).
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    discord_oauth_client_id: str = ""
    discord_oauth_client_secret: str = ""
    initial_admin_github_id: str = ""
    initial_admin_email: str = ""

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
    # Reused as-is by #221's traffic rollup below — same zone, no reason
    # for a second env var just to hold the same value twice.
    cloudflare_zone_id: str = "090a6d6b91e55f92740f23bad2c11de6"
    public_site_base_url: str = "https://anifillerpedia.wiki"

    # #221 (implementation of #219's decision): daily Cloudflare zone-
    # analytics rollup. A *separate* token from cloudflare_api_token above
    # — that one is scoped to Zone > Cache Purge for #15's outbox
    # consumer, this one needs a narrower Zone > Analytics > Read scope
    # for this zone only, so they're kept as two distinct credentials
    # rather than one token doing double duty across two different
    # privilege scopes. Not provisioned yet (CLAUDE.local.md's external-
    # account checklist) — empty by default, same "structurally ready,
    # not live-configured" pattern as telegram_bot_token/turnstile_secret_key
    # above: services/traffic_analytics.py's daily loop logs once and
    # no-ops while this is unset, rather than erroring or crash-looping.
    cloudflare_analytics_api_token: str = ""

    # Daily by default, same reasoning as episode_schedule_sync_interval_
    # seconds above — this data only needs a once-a-day rollup, not a
    # tight poll loop.
    traffic_rollup_interval_seconds: int = 60 * 60 * 24


_INSECURE_DEFAULT_SESSION_SECRET_KEY = "dev-insecure-change-me"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Security review (#89): this default is committed in this repo's own
    # source — publicly readable — so running production with it means
    # anyone can forge a valid session cookie (itsdangerous signature) for
    # any user_id, including admin/owner. Refuse to start rather than rely
    # on remembering to set a real one in .env.
    if (
        settings.environment != "development"
        and settings.session_secret_key == _INSECURE_DEFAULT_SESSION_SECRET_KEY
    ):
        raise RuntimeError(
            "SESSION_SECRET_KEY is unset or still the insecure default while "
            f"ENVIRONMENT={settings.environment!r} — refusing to start. Set a "
            "real SESSION_SECRET_KEY in .env (e.g. `python3 -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\"`)."
        )
    return settings
