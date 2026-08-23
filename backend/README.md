# backend/

FastAPI + async SQLAlchemy Core (raw SQL via `text()`, no ORM) on Postgres.
Layered `routers/` → `services/` → `repositories/`, plus `schemas/` for
Pydantic request/response models and `core/` for cross-cutting concerns
(db session, auth/session cookies, config). `worker.py` is a separate
process — see **Outbox worker** below.

## Running locally

Needs a local Postgres — the repo's own `docker-compose.yml` is the
*production* deploy stack (six services, meant for the droplet), not a
lightweight local-dev shortcut, so spin up just Postgres yourself:

```sh
docker run -d --name afp-postgres \
  -e POSTGRES_USER=anifillerpedia -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=anifillerpedia -p 5432:5432 postgres:16-alpine

psql postgresql://anifillerpedia:changeme@localhost:5432/anifillerpedia -f schema.sql
```

(`schema.sql` is the full current-state schema for a fresh install — the
numbered files in `migrations/` are for bringing an *existing* database
up to date, not needed on a brand-new one.)

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in DATABASE_URL to match the container above
.venv/bin/uvicorn main:app --reload
```

`GET /api/v1/health` should return `{"status": "ok"}`. Interactive API docs
at `/docs`, the raw OpenAPI schema at `/openapi.json` (what the frontend's
typed client is generated from — see `frontend/README.md`).

## Testing

```sh
DATABASE_URL=postgresql+asyncpg://anifillerpedia:changeme@localhost:5432/anifillerpedia \
  .venv/bin/python -m pytest
```

Every test runs against a real Postgres instance — no mocks, matching this
project's own stated preference (see `CLAUDE.md`). Tests create their own
prefixed rows (`__test_N__...`) and clean up everything they insert, so
it's safe to run against a database that already has real bootstrap data
loaded (`data/bootstrap/`) — nothing here touches a row it didn't create.

## Outbox worker

`worker.py` is a separate long-running process, not part of the FastAPI
app itself — it polls the `outbox_events` table (`FOR UPDATE SKIP LOCKED`)
and dispatches side effects (a moderator Telegram notification on a new
pending contribution, a Cloudflare cache purge on approval). Postgres is
the broker here, not a message queue — see `CLAUDE.md` Architecture for
why. Run it alongside the app with the same `DATABASE_URL`:

```sh
.venv/bin/python worker.py
```

Both `TELEGRAM_BOT_TOKEN` and `CLOUDFLARE_API_TOKEN` are optional — left
blank, the relevant handler logs a warning and skips rather than crashing
the whole worker.

## Bootstrap / data-ops scripts

`data/bootstrap/` (repo root, not under `backend/`) holds the one-off
scripts that load hand-compiled episode data and the initial series
catalog — `load_series.py`, `load_episodes.py`, and the AniList-backed
`backfill_episode_titles_from_anilist.py`. These use plain sync
`psycopg2`, not this app's async stack, and are run directly against
`DATABASE_URL` rather than through the API. See that directory's own
`README.md` for the JSON format they expect and what's been loaded so far.
