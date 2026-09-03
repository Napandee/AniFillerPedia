"""AniFillerPedia MCP server — Phase 1 (read-only), issue #178.

Exposes 5 tools wrapping AniFillerPedia's existing public REST API over
HTTP/SSE (the `streamable-http` MCP transport), so any visitor's AI client
can reach it over the network rather than needing a locally-spawned stdio
process (#159's decision). This server never touches Postgres directly —
`afp_client.py` is the only thing that talks to the outside world, and it
only ever calls the same public, unauthenticated read endpoints the Astro
frontend calls.

Uses the official `mcp` Python SDK (PyPI package `mcp`, currently on its
v2 line — confirmed via `pip index versions mcp` during development,
2026-09-03; v2 renamed the old `FastMCP` class to `MCPServer`, which is
what's used below). Every tool response embeds a compact `_license` field
(see `_attribution()`) mirroring `/export`'s own embedded attribution
manifest — pulled from a real `GET /license` call cached at server
startup via the lifespan context, not hardcoded text that could drift
from the real license (#159's decision point 5).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

import afp_client

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_STREAMABLE_HTTP_PATH = "/mcp"
"""Matches `mcp.server.mcpserver.MCPServer.run`'s own default — kept
explicit here (rather than relying on the SDK default silently) because
the Caddyfile's `/mcp` route depends on this exact path lining up with no
extra prefix-stripping on either side."""


@dataclass
class AppContext:
    license_info: dict[str, Any]


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    """Fetch the license/attribution manifest once at startup and cache it
    for the life of the process — every tool call reads the cached copy
    (see `_attribution` below) instead of re-hitting `GET /license` on
    every single call, per #159's decision point 5.

    If the backend isn't reachable yet at startup (e.g. a cold-start race
    against the `app` container), fall back to a conservative static
    manifest rather than crashing the whole MCP server — an MCP client
    that can't reach `search_series` etc. either way isn't helped by this
    process refusing to start, and the fallback still carries the real
    license name and a pointer to where the authoritative version lives.
    """
    try:
        license_info = await afp_client.get_license()
    except Exception:
        license_info = {
            "license": "CC BY-NC-SA 4.0",
            "attribution_notice": (
                "Contains information from AniFillerPedia, which is made "
                "available here under CC BY-NC-SA 4.0 (non-commercial use; "
                "contact us for a commercial license)."
            ),
            "commercial_licensing_contact": (
                "See https://github.com/Napandee/AniFillerPedia DATA_LICENSE "
                "for the current commercial-licensing contact channel."
            ),
            "dataset_license_url": (
                "https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE"
            ),
        }
    yield AppContext(license_info=license_info)


mcp = MCPServer(
    "anifillerpedia",
    title="AniFillerPedia",
    version="0.1.0",
    instructions=(
        "Read-only tools over AniFillerPedia's public API: a community-"
        "editable database of anime filler/canon/mixed episode data. "
        "Every tool response carries a `_license` field — the dataset is "
        "CC BY-NC-SA 4.0 (free to read/reuse non-commercially with "
        "attribution; a paid product needs a separate commercial "
        "agreement, see the embedded `commercial_licensing_contact`)."
    ),
    lifespan=app_lifespan,
)


def _attribution(ctx: Context) -> dict[str, Any]:
    """The compact `_license` field embedded in every tool response
    (#159's decision point 5) — read from the lifespan-cached manifest,
    not re-fetched per call."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    license_info = app_ctx.license_info
    return {
        "name": license_info.get("license"),
        "attribution_notice": license_info.get("attribution_notice"),
        "commercial_contact": license_info.get("commercial_licensing_contact"),
        "url": license_info.get("dataset_license_url"),
    }


def _with_attribution(payload: Any, ctx: Context) -> dict[str, Any]:
    """Wrap a raw API payload (dict or list) with the `_license` field.

    A list response (e.g. `get_episodes`) can't carry an extra top-level
    key on itself, so it's wrapped under an `episodes` key instead — every
    tool response is a JSON *object* with `_license` alongside the real
    data, never a bare array, so a client can rely on that shape uniformly.
    """
    if isinstance(payload, list):
        return {"episodes": payload, "_license": _attribution(ctx)}
    return {**payload, "_license": _attribution(ctx)}


@mcp.tool()
async def search_series(query: str, ctx: Context, limit: int = 20) -> dict[str, Any]:
    """Search AniFillerPedia's series catalog by title or known synonym
    (alternate/romanized/native-script titles all match). Also accepts an
    external id lookup server-side (anilist_id/mal_id/anidb_id) via the
    underlying API, but this tool's own signature only exposes the
    free-text `query` — use `get_series` directly if you already have a
    numeric series id or slug.

    Returns up to `limit` (default 20, max 100) matching series, each with
    its `id` and `slug` — either can be passed to `get_series`/
    `get_episodes`.
    """
    result = await afp_client.search_series(query=query, limit=limit)
    return _with_attribution(result, ctx)


@mcp.tool()
async def get_series(id_or_slug: str, ctx: Context) -> dict[str, Any]:
    """Get full detail for one series by its numeric id or slug (both
    resolve indefinitely — either is a stable identifier). Includes
    synonyms, AniList's own episode count/synopsis/air-date range (where
    synced), airing status, and links to related catalog entries for
    franchises split across multiple AniList entries (e.g. Fairy Tail's
    three separate catalog rows).
    """
    result = await afp_client.get_series(id_or_slug=id_or_slug)
    return _with_attribution(result, ctx)


@mcp.tool()
async def get_episodes(series_id_or_slug: str, ctx: Context) -> dict[str, Any]:
    """List every episode AniFillerPedia has researched for one series
    (by numeric series id or slug), each with its canon/filler/mixed
    `status`, citation (source(s) the classification is based on), and
    title/air date where known. Absence of an episode row means "not
    researched yet", not "canon by default" — there is no row for an
    episode nobody has looked into.
    """
    result = await afp_client.get_episodes(series_id_or_slug=series_id_or_slug)
    return _with_attribution(result, ctx)


@mcp.tool()
async def get_episode(episode_id: int, ctx: Context) -> dict[str, Any]:
    """Get one episode by its own numeric episode id (not its
    episode_number within a series — use `get_episodes` to find the right
    id first). Same shape as one entry from `get_episodes`.
    """
    result = await afp_client.get_episode(episode_id=episode_id)
    return _with_attribution(result, ctx)


@mcp.tool()
async def get_license(ctx: Context) -> dict[str, Any]:
    """Get AniFillerPedia's dataset license terms directly: CC BY-NC-SA
    4.0 — free to read and reuse non-commercially with attribution; a
    paid product needs a separate commercial agreement (see the returned
    `commercial_licensing_contact`). The code powering the API is
    separately MIT-licensed. Every other tool's response already embeds
    this same information under `_license`; call this directly only if
    you want the full manifest on its own.
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return _with_attribution(app_ctx.license_info, ctx)


def main() -> None:
    host = os.environ.get("MCP_HOST", DEFAULT_HOST)
    port = int(os.environ.get("MCP_PORT", str(DEFAULT_PORT)))
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=DEFAULT_STREAMABLE_HTTP_PATH,
    )


if __name__ == "__main__":
    main()
