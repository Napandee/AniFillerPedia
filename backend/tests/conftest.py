"""pytest-asyncio gives each test function its own event loop
(`asyncio_default_fixture_loop_scope = function`, pytest.ini), but
core.db's async engine + connection pool are created once at import time
and bound to whichever loop is running then. Reusing that pool from a
later test's *different* loop corrupts it (asyncpg raises "another
operation is in progress" for what looks like an unrelated query). Dispose
the engine after every test so the next one starts a clean pool on its own
loop.
"""

import json
import urllib.error
import urllib.request

import pytest
import pytest_asyncio
from sqlalchemy import text

from core.db import async_session_factory, engine

ANILIST_URL = "https://graphql.anilist.co"


def _anilist_reachable() -> tuple[bool, str]:
    """Probe the public AniList API once per session.

    tests/test_anilist_lookup.py and tests/test_anilist_sync.py deliberately
    hit the real API rather than mocking it, so they catch upstream schema
    changes. The cost is that AniList's availability gates them — and because
    branch protection requires the `build` check those tests run inside, an
    AniList outage blocks every merge in this repo, including docs-only ones.

    That happened for real: from 2026-09-04 the API returned
    403 "The AniList API has been temporarily disabled due to severe
    stability issues", which turned the required check red on six consecutive
    unrelated PRs.

    So probe first and skip when it is down. The tests still run — and still
    catch upstream changes — the moment AniList is answering again. This is
    deliberately not a mock: mocking would make them pass while blind to the
    very changes they exist to detect.
    """
    body = json.dumps({"query": "{Media(id:1,type:ANIME){id}}"}).encode()
    req = urllib.request.Request(
        ANILIST_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return False, f"AniList API returned HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any transport failure means "unreachable"
        return False, f"AniList API unreachable: {type(exc).__name__}"
    if payload.get("errors"):
        return False, f"AniList API error: {payload['errors'][0].get('message', '?')}"
    if not (payload.get("data") or {}).get("Media"):
        return False, "AniList API returned no data for a known id"
    return True, ""


def pytest_collection_modifyitems(config, items):
    if not any("live_network" in item.keywords for item in items):
        return
    ok, why = _anilist_reachable()
    if ok:
        return
    skip = pytest.mark.skip(reason=f"{why} — skipping live-network tests (see conftest)")
    for item in items:
        if "live_network" in item.keywords:
            item.add_marker(skip)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clear_rate_limit_events():
    """#139/#141: rate_limit_events (repositories/rate_limits.py) is
    transient IP/user-keyed rate-limit bookkeeping with no audit-trail
    purpose — cleared before every test so one test's anonymous
    submissions (many tests in this suite POST /contributions or
    /series-proposals without a session cookie, sharing the same test
    client "IP") never spuriously count against a completely unrelated
    test's own rate-limit budget, and so re-running the suite repeatedly
    inside the same real hour never accumulates stale counts either.
    """
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM rate_limit_events"))
    yield
