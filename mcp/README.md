# AniFillerPedia MCP server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server
exposing AniFillerPedia's public REST API as 5 tools, so an MCP-aware AI
client (Claude Desktop, Claude Code, or anything else speaking MCP) can look
up anime filler/canon episode data directly, without a human going through
the website or the raw REST API.

This is Phase 1 only — read-only. See
[issue #178](https://github.com/Napandee/AniFillerPedia/issues/178) and the
[#159 design decision](https://github.com/Napandee/AniFillerPedia/issues/159)
it implements. Phase 2 (write/contribution tools) is explicitly out of
scope, blocked on an unsolved MCP-auth design question.

## What this is (and isn't)

- A **third top-level directory** in this monorepo, alongside `backend/` and
  `frontend/` — same hard-separation convention (CLAUDE.md Guardrails): no
  shared config/tooling/dependency files with either.
- A **thin wrapper**, not a reimplementation. Every tool is a direct HTTP
  call to an existing public endpoint on the real API
  (`afp_client.py`) — this service never touches Postgres directly, the same
  way the Astro frontend doesn't either.
- **HTTP/SSE (`streamable-http`) transport**, not stdio — deployed as its
  own container, reachable over the network at `/mcp` on the public domain,
  not spawned locally by a client process.

## Tools

| Tool | Wraps | Notes |
|---|---|---|
| `search_series(query, limit=20)` | `GET /api/v1/series?q=...&limit=...` | Title/synonym search. The wire parameter is `q`, not `query` — verified against the live OpenAPI schema during development, since #159's original sketch had this wrong. |
| `get_series(id_or_slug)` | `GET /api/v1/series/{id_or_slug}` | Accepts either the numeric id or the slug — both resolve indefinitely. |
| `get_episodes(series_id_or_slug)` | `GET /api/v1/series/{id}/episodes` | A slug is resolved to its numeric id first (one extra internal call to `get_series`) since the underlying endpoint's path parameter is typed as an integer on the wire. |
| `get_episode(episode_id)` | `GET /api/v1/episodes/{episode_id}` | By the episode's own numeric id — not its `episode_number` within a series. |
| `get_license()` | `GET /api/v1/license` | The full attribution manifest on its own — every other tool already embeds the same information under `_license` (see below). |

See [`docs/API.md`](../docs/API.md) for the underlying REST API's own full
documentation (request/response shapes, error codes, etc.) — this file
covers the MCP layer specifically, not the API it wraps.

## Attribution

**Every tool response embeds a compact `_license` field**, e.g.:

```json
{
  "...": "...(the real tool result)...",
  "_license": {
    "name": "CC BY-NC-SA 4.0",
    "attribution_notice": "Contains information from AniFillerPedia, which is made available here under CC BY-NC-SA 4.0 (non-commercial use; contact us for a commercial license).",
    "commercial_contact": "See https://github.com/Napandee/AniFillerPedia DATA_LICENSE for the current commercial-licensing contact channel.",
    "url": "https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE"
  }
}
```

This mirrors `/export`'s own embedded attribution manifest, for the same
reason: an AI agent consuming a tool response is exactly as disconnected
from the live API docs as a downloaded export file is, so the license terms
travel with the data itself rather than requiring a separate lookup. The
values are fetched once from the real `GET /api/v1/license` endpoint at
server startup and cached for the process's lifetime (see `server.py`'s
`app_lifespan`) — not hardcoded text that could drift from the real,
authoritative license.

A response whose real payload is a JSON array (`get_episodes`) is wrapped
under an `episodes` key so `_license` has somewhere to live alongside it —
every tool response is a JSON object, never a bare array.

## Running locally

```bash
cd mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Point at a local backend, or the real production API:
export AFP_API_BASE_URL=http://127.0.0.1:8000        # local backend/
# export AFP_API_BASE_URL=https://anifillerpedia.wiki/api/v1

python server.py
# Streamable-HTTP endpoint listening at http://0.0.0.0:8000/mcp
```

`MCP_HOST`/`MCP_PORT` override the bind address/port (default
`0.0.0.0:8000`, matching the container's own `EXPOSE 8000`).

## Testing

```bash
cd mcp
python -m pytest -v
```

- `tests/test_afp_client.py` — unit tests for the HTTP wrapper layer, with
  `httpx.AsyncClient.get` mocked (precedented in this repo — see
  `backend/tests/test_anilist_sync.py`'s own split between mocked
  pure-function tests and real-dependency tests).
- `tests/test_server_integration.py` — a real end-to-end test: spins up the
  actual `MCPServer` on a real `streamable-http` ASGI app (uvicorn, a real
  localhost socket) and drives it with the official `mcp` SDK's own client
  (`mcp.client.streamable_http` + `mcp.client.session.ClientSession`) — not
  by calling the tool functions directly in-process. Hits the **real,
  deployed production API** by default
  (`https://anifillerpedia.wiki/api/v1`), matching this repo's own
  established "test against the real dependency, not a stand-in"
  convention (`backend/tests/test_anilist_sync.py`'s header comment) —
  override `AFP_API_BASE_URL` before running pytest to point it elsewhere
  (e.g. a local `backend/` + test-pg stack) instead.

## Deployment

Same self-hosted-runner deploy pattern as `app`/`worker`/`frontend`
(`docker-compose.yml`'s `mcp` service; `.github/workflows/mcp-validate.yml`
+ `mcp-deploy.yml`, both path-filtered to `mcp/**` only). The container
listens on `:8000` internally; `Caddyfile` routes the public `/mcp` path to
it — **that Caddyfile change requires explicit sign-off before merging**,
per this repo's own deploy-pipeline guardrail (see #178).

`AFP_API_BASE_URL` defaults to `http://app:8000` — the internal Docker
network hostname the `frontend` container already uses to reach the backend
the same way (see `docker-compose.yml`'s `frontend` service and its own
`PUBLIC_API_BASE_URL` build arg for the precedent).

## Package/SDK choice

Uses the official [`mcp`](https://pypi.org/project/mcp/) Python SDK,
currently on its v2 line (`mcp==2.1.1` as of this writing, confirmed via
`pip index versions mcp` during development rather than assumed). v2
renamed the old `FastMCP` class to `MCPServer` — this codebase uses the
current name (`from mcp.server.mcpserver import MCPServer`), not the
deprecated v1 API.
