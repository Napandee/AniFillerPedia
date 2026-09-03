"""Thin async HTTP wrapper around AniFillerPedia's public REST API.

This module never touches Postgres — it's just another consumer of the
same public, unauthenticated read endpoints the Astro frontend calls (see
CLAUDE.md's "one contract... any external consumer" architecture note).
Every function here maps 1:1 onto one GET endpoint documented in
`docs/API.md`; parameter/response shapes were verified directly against
the real, deployed OpenAPI schema (`GET /openapi.json`) rather than
assumed from #159's original sketch — notably, series search takes `q`,
not `query`, on the wire (this module's own `search_series` keeps the
friendlier `query` name for its *caller*, translating to `q` only in the
outgoing request).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://app:8000"
"""Internal docker-network hostname for the `app` service — see
docker-compose.yml's `frontend` service, which reaches the backend the
same way (`PUBLIC_API_BASE_URL: http://app:8000`) rather than round-
tripping out through Caddy and back in. Overridable via `AFP_API_BASE_URL`
for local development (e.g. against `http://127.0.0.1:8000` or the real
`https://anifillerpedia.wiki/api/v1`)."""

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class AFPAPIError(Exception):
    """Raised when the upstream AniFillerPedia API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"AniFillerPedia API returned {status_code}: {detail!r}")


def get_base_url() -> str:
    """Read `AFP_API_BASE_URL` at call time (not import time) so tests can
    override it via `monkeypatch.setenv` without needing a process restart.
    Trailing slashes are stripped so callers can join paths unconditionally.
    """
    return os.environ.get("AFP_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_v1_url(path: str) -> str:
    base = get_base_url()
    # `docker-compose.yml`'s AFP_API_BASE_URL points straight at the `app`
    # container root (no /api/v1 prefix — Caddy adds that split only for
    # the public domain), but a caller pointing this at the real public
    # domain (https://anifillerpedia.wiki) needs the prefix. Handle both:
    # if the base URL already ends in /api/v1, don't double it up.
    if base.endswith("/api/v1"):
        return f"{base}{path}"
    return f"{base}/api/v1{path}"


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = _api_v1_url(path)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(url, params=params)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise AFPAPIError(response.status_code, detail)
    return response.json()


async def search_series(query: str, limit: int = 20) -> dict[str, Any]:
    """`GET /api/v1/series?q=...&limit=...` — title/synonym search.

    The wire parameter is `q` (confirmed via the live OpenAPI schema); this
    wrapper's own `query` argument name is kept because it's clearer to an
    MCP tool caller than the API's own terse `q`.
    """
    return await _get("/series", params={"q": query, "limit": limit})


async def get_series(id_or_slug: str) -> dict[str, Any]:
    """`GET /api/v1/series/{id_or_slug}` — accepts either the numeric id or
    the slug; both resolve indefinitely per docs/API.md."""
    return await _get(f"/series/{id_or_slug}")


async def get_episodes(series_id_or_slug: str) -> list[dict[str, Any]]:
    """`GET /api/v1/series/{id}/episodes`.

    The real endpoint's path parameter is typed `int` on the wire (see the
    OpenAPI schema — `series_id: integer`), unlike `GET /series/{id_or_slug}`
    which genuinely accepts either form. A slug passed here is resolved to
    its numeric id first via `get_series`, so this tool's own
    `series_id_or_slug` naming (matching #159's decision) still works for a
    caller who only has a slug in hand.
    """
    if series_id_or_slug.lstrip("-").isdigit():
        series_id = series_id_or_slug
    else:
        series = await get_series(series_id_or_slug)
        series_id = str(series["id"])
    return await _get(f"/series/{series_id}/episodes")


async def get_episode(episode_id: int) -> dict[str, Any]:
    """`GET /api/v1/episodes/{episode_id}`."""
    return await _get(f"/episodes/{episode_id}")


async def get_license() -> dict[str, Any]:
    """`GET /api/v1/license` — the structured attribution manifest
    (`ExportManifest` in the OpenAPI schema: `license`, `attribution_notice`,
    `commercial_licensing_contact`, `dataset_license_url`). Fetched once at
    server startup and cached — see `server.py`'s lifespan — rather than
    re-fetched on every single tool call, per #159's decision."""
    return await _get("/license")
