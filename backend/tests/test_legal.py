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
    assert "DELETE /api/v1/users/me" in body  # #29 shipped — no longer "planned but not yet built"


@pytest.mark.asyncio
async def test_license_endpoint_reachable() -> None:
    """#21's dedicated attribution endpoint — decided but never actually
    built until found missing while writing #16's API docs.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/license")
    assert response.status_code == 200
    body = response.json()
    assert body["license"] == "CC BY-NC-SA 4.0"
    assert "commercial" in body["attribution_notice"].lower()
    assert body["dataset_license_url"].endswith("DATA_LICENSE")


@pytest.mark.asyncio
async def test_openapi_schema_reports_correct_license() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    license_info = response.json()["info"]["license"]
    assert "CC BY-NC-SA" in license_info["name"]
    assert "MIT" in license_info["name"]
