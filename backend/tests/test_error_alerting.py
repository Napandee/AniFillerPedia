"""#17: unhandled application errors -> Telegram alert.

No real TELEGRAM_BOT_TOKEN exists yet (see CLAUDE.local.md's external-
account checklist) so these tests mock the Telegram-send boundary
(services.alerting.alert_unhandled_exception, and separately
services.telegram.send_telegram_message for the worker's poll-loop path)
rather than making real Telegram API calls — consistent with how
test_outbox_consumers.py already tests #15's notification/purge handlers.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from worker import run_forever


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_and_fires_alert(monkeypatch) -> None:
    mock_alert = AsyncMock()
    monkeypatch.setattr("main.alert_unhandled_exception", mock_alert)

    @app.get("/api/v1/_test_only_unhandled_boom")
    async def _boom() -> None:
        raise RuntimeError("simulated unhandled error — test only")

    # raise_app_exceptions=False: Starlette's ServerErrorMiddleware always
    # re-raises after sending the response (by design, so servers/test
    # clients can see it) — this tells httpx's ASGI transport not to
    # propagate that re-raise into the test, so we can assert on the
    # response our own handler actually returned instead.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/_test_only_unhandled_boom")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}

        # The alert is fired via asyncio.create_task (fire-and-forget) —
        # give the event loop one tick to actually run it.
        await asyncio.sleep(0)
        mock_alert.assert_called_once()
        context_arg, exc_arg = mock_alert.call_args[0]
        assert "GET" in context_arg and "_test_only_unhandled_boom" in context_arg
        assert isinstance(exc_arg, RuntimeError)
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) != "/api/v1/_test_only_unhandled_boom"
        ]


@pytest.mark.asyncio
async def test_intentional_http_exception_does_not_fire_alert(monkeypatch) -> None:
    """A deliberate HTTPException (404/403/etc, already raised throughout
    this app) must NOT be treated as an unhandled error — confirms the
    Exception handler doesn't shadow FastAPI's own HTTPException handling.
    """
    mock_alert = AsyncMock()
    monkeypatch.setattr("main.alert_unhandled_exception", mock_alert)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/series/999999999")
    assert response.status_code == 404
    await asyncio.sleep(0)
    mock_alert.assert_not_called()


@pytest.mark.asyncio
async def test_worker_poll_loop_alerts_on_unhandled_exception(monkeypatch) -> None:
    mock_alert = AsyncMock()
    monkeypatch.setattr("worker.alert_unhandled_exception", mock_alert)

    async def _raising_process_batch() -> int:
        raise RuntimeError("simulated worker failure — test only")

    monkeypatch.setattr("worker.process_batch", _raising_process_batch)

    # run_forever loops forever; let one iteration (which raises, alerts,
    # then hits the poll-interval sleep) happen, then cancel via timeout
    # rather than trying to break the loop from the outside.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(run_forever(), timeout=0.2)

    mock_alert.assert_called_once()
    context_arg, exc_arg = mock_alert.call_args[0]
    assert context_arg == "outbox worker poll loop"
    assert isinstance(exc_arg, RuntimeError)
