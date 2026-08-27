"""pytest-asyncio gives each test function its own event loop
(`asyncio_default_fixture_loop_scope = function`, pytest.ini), but
core.db's async engine + connection pool are created once at import time
and bound to whichever loop is running then. Reusing that pool from a
later test's *different* loop corrupts it (asyncpg raises "another
operation is in progress" for what looks like an unrelated query). Dispose
the engine after every test so the next one starts a clean pool on its own
loop.
"""

import pytest_asyncio
from sqlalchemy import text

from core.db import async_session_factory, engine


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
