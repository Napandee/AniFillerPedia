import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_privacy_policy_is_reachable() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/privacy")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    # The substance that actually matters for Google's review and for GDPR:
    # what's collected, how deletion works, that anonymous use needs no account.
    assert "GitHub" in body and "Discord" in body
    assert "anonymous" in body.lower()
    assert "14 days" in body
    assert "DATA_LICENSE" in body
