import pytest
from httpx import ASGITransport, AsyncClient

from core.version import API_VERSION
from main import app


@pytest.mark.asyncio
async def test_health() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    # DELIBERATE BREAK for #188 CI-wiring verification — reverted before merge.
    assert response.json() == {"status": "definitely-not-ok"}


@pytest.mark.asyncio
async def test_version() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/version")
    assert response.status_code == 200
    assert response.json() == {"version": API_VERSION}
