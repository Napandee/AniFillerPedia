"""Real MCP-client-protocol integration test — spins up the actual
MCPServer over its real `streamable-http` ASGI app (uvicorn, a real
socket on localhost) and drives it with the official `mcp` SDK's own
client (`mcp.client.streamable_http` + `mcp.client.session.ClientSession`),
not by calling the tool functions directly in-process. This is the "prove
the server itself works, not just its internals" test the issue asks for.

Hits the REAL, deployed AniFillerPedia production API
(https://anifillerpedia.wiki/api/v1) by default — matching this repo's
own established convention (see backend/tests/test_anilist_sync.py's
header comment: "test against the real dependency, not a stand-in")
rather than mocking. It's a public, unauthenticated, read-only GET API
with no rate-limit wall for reasonable use (see docs/API.md), so a
handful of read calls per CI run is exactly the kind of "reasonable use"
that guarantee exists for. Override `AFP_API_BASE_URL` (e.g. to point at
a local backend/test-pg stack) if you're iterating offline — see
mcp/README.md.

Uses Naruto: Shippuuden (a permanently-finished, fully-researched show,
same one backend/tests/test_anilist_sync.py already anchors on for the
same "stable real fixture" reason) resolved dynamically via
`search_series` rather than a hardcoded series/episode id, so a future
catalog change (a corrected id, a re-run bootstrap) can't silently break
this test the way a hardcoded id could.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

import server as afp_mcp_server

_PORT = 8933
_MCP_URL = f"http://127.0.0.1:{_PORT}/mcp"


@pytest_asyncio.fixture
async def running_server() -> AsyncIterator[None]:
    app = afp_mcp_server.mcp.streamable_http_app(streamable_http_path="/mcp")
    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="warning")
    server = uvicorn.Server(config)

    # Plain asyncio.create_task rather than an anyio.create_task_group here
    # — the latter enforces structured concurrency (the task group's scope
    # must be entered/exited in the same task), which doesn't line up with
    # how a pytest-asyncio async fixture's setup and teardown (the code
    # before/after `yield`) can run across a fixture-management boundary.
    serve_task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        raise RuntimeError("test MCP server never started listening")
    try:
        yield
    finally:
        server.should_exit = True
        await serve_task


def _first_text_payload(result: CallToolResult) -> str:
    assert not result.is_error, f"tool call returned an error: {result.content}"
    assert result.content and result.content[0].type == "text"
    return result.content[0].text


def _assert_has_attribution(payload: dict) -> None:
    """The #159/#178 requirement: every tool response embeds `_license`."""
    assert "_license" in payload
    license_field = payload["_license"]
    assert license_field["name"] == "CC BY-NC-SA 4.0"
    assert license_field["commercial_contact"]
    assert license_field["url"]


@pytest.mark.asyncio
async def test_all_five_tools_are_advertised(running_server: None) -> None:
    async with streamable_http_client(_MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {
                "search_series",
                "get_series",
                "get_episodes",
                "get_episode",
                "get_license",
            }


@pytest.mark.asyncio
async def test_search_series_returns_matches_with_attribution(running_server: None) -> None:
    import json

    async with streamable_http_client(_MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_series", {"query": "Naruto: Shippuuden", "limit": 5})
            payload = json.loads(_first_text_payload(result))
            assert "items" in payload
            assert len(payload["items"]) >= 1
            _assert_has_attribution(payload)


@pytest.mark.asyncio
async def test_full_tool_chain_search_series_episodes_episode_license(running_server: None) -> None:
    """Exercises all 5 tools in one realistic chain, each result feeding
    the next — the way a real MCP client would actually use this server,
    and resilient to the underlying catalog data changing over time."""
    import json

    async with streamable_http_client(_MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            search_result = await session.call_tool(
                "search_series", {"query": "Naruto: Shippuuden", "limit": 5}
            )
            search_payload = json.loads(_first_text_payload(search_result))
            _assert_has_attribution(search_payload)
            assert search_payload["items"], "expected at least one match for a well-known, long-loaded show"
            series = search_payload["items"][0]
            assert series["id"] and series["slug"]

            series_result = await session.call_tool("get_series", {"id_or_slug": series["slug"]})
            series_payload = json.loads(_first_text_payload(series_result))
            _assert_has_attribution(series_payload)
            assert series_payload["id"] == series["id"]
            assert series_payload["slug"] == series["slug"]

            episodes_result = await session.call_tool(
                "get_episodes", {"series_id_or_slug": series["slug"]}
            )
            episodes_payload = json.loads(_first_text_payload(episodes_result))
            _assert_has_attribution(episodes_payload)
            assert "episodes" in episodes_payload
            assert episodes_payload["episodes"], "Naruto: Shippuuden is fully researched (500/500 episodes)"
            first_episode = episodes_payload["episodes"][0]
            assert first_episode["status"] in {"canon", "filler", "mixed"}
            assert first_episode["citation"] is not None

            episode_result = await session.call_tool("get_episode", {"episode_id": first_episode["id"]})
            episode_payload = json.loads(_first_text_payload(episode_result))
            _assert_has_attribution(episode_payload)
            assert episode_payload["id"] == first_episode["id"]
            assert episode_payload["series_id"] == series["id"]

            license_result = await session.call_tool("get_license", {})
            license_payload = json.loads(_first_text_payload(license_result))
            _assert_has_attribution(license_payload)
            assert license_payload["license"] == "CC BY-NC-SA 4.0"


@pytest.mark.asyncio
async def test_get_series_with_unknown_slug_returns_a_tool_error(running_server: None) -> None:
    """The upstream API's 404 (AFPAPIError) should surface as a tool-level
    error via the MCP protocol's own error envelope, not crash the server
    or the calling client's session."""
    async with streamable_http_client(_MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_series", {"id_or_slug": "definitely-not-a-real-series-slug-__test__"}
            )
            assert result.is_error
