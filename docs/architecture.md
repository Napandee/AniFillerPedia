# Architecture

How the backend, frontend and database fit together.

Built and live, matching the shape decided in the 2026-08-20 planning
session:

- **API**: FastAPI, `/api/v1/...`, layered routers/services/repositories.
  Public read endpoints (series, episodes, per-episode citation, per-episode
  contribution history) are unauthenticated. Contribution/series-proposal
  submission requires GitHub OAuth login (any contributor); approval/rejection
  requires moderator/admin role. Same API serves both the public Astro
  frontend (via a typed client generated from FastAPI's own OpenAPI schema)
  and any external consumer (e.g. a future AniDex integration) — one contract,
  no separate internal API.
- **Async/side-effects**: transactional outbox pattern, not a message broker.
  An `outbox_events` table is written to in the same DB transaction as any
  state change other systems care about (contribution submitted/approved/
  rejected, series proposal submitted/approved). A separate lightweight
  worker container polls it (`FOR UPDATE SKIP LOCKED`) and dispatches side
  effects (moderator Telegram notification on new pending contribution,
  Cloudflare cache purge on approval so public pages refresh immediately
  rather than waiting on a cache TTL). Postgres is the broker — no Redis/
  Celery. Chosen deliberately over waiting to add this later: the
  write-path/schema stay unchanged if real scale ever justifies swapping the
  poller for a heavier Postgres-backed queue library or running more worker
  replicas — only the consumer side would change.
- **Frontend**: Astro, server-rendered (SSR/on-demand) for series/episode
  pages rather than a full static prebuild — avoids needing any
  rebuild-trigger pipeline to propagate approved changes; freshness instead
  comes from the outbox-driven cache purge above. Islands for auth, search,
  the contribution submission form, and the moderator approval-queue view.

- **MCP server** (`mcp/`, decided 2026-08-27 issue #159, built #178): a
  standalone, read-only Model Context Protocol server — 5 GET-only tool
  wrappers (search/get series, get episodes, get episode, get license) over
  the same public REST API, never touching Postgres directly. Its own
  container, its own path-filtered CI, routed at `/mcp` through Caddy —
  same hard-separation convention as `backend/`/`frontend/`. Write tools are
  explicitly out of scope (blocked on an unsolved MCP-auth design problem).
