"""Unit tests for afp_client.py's request-building/response-shaping logic,
with the HTTP boundary mocked — precedented in this repo by
backend/tests/test_anilist_sync.py's own split (pure-function unit tests
mocked/isolated, real-dependency tests separate). The real-dependency
counterpart for this module lives in test_server_integration.py, which
drives the whole stack (including afp_client's real HTTP calls) through
the actual MCP client protocol against a real API.

Mocks `httpx.AsyncClient.get` directly (class-level monkeypatch) rather
than pulling in a mocking library like `respx` — a single well-known
method on a well-known class is simple enough not to need one.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

import afp_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self) -> Any:
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def _reset_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AFP_API_BASE_URL", raising=False)


def _mock_get(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> AsyncMock:
    mock = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "get", mock)
    return mock


def test_get_base_url_defaults_to_internal_docker_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AFP_API_BASE_URL", raising=False)
    assert afp_client.get_base_url() == "http://app:8000"


def test_get_base_url_reads_env_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AFP_API_BASE_URL", "http://127.0.0.1:9000")
    assert afp_client.get_base_url() == "http://127.0.0.1:9000"


def test_api_v1_url_adds_prefix_for_bare_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AFP_API_BASE_URL", "http://app:8000")
    assert afp_client._api_v1_url("/series") == "http://app:8000/api/v1/series"


def test_api_v1_url_does_not_double_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AFP_API_BASE_URL", "https://anifillerpedia.wiki/api/v1")
    assert afp_client._api_v1_url("/series") == "https://anifillerpedia.wiki/api/v1/series"


def test_api_v1_url_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AFP_API_BASE_URL", "http://app:8000/")
    assert afp_client._api_v1_url("/series") == "http://app:8000/api/v1/series"


@pytest.mark.asyncio
async def test_search_series_translates_query_to_q_on_the_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool-facing argument is `query`; the real wire parameter (per
    the live OpenAPI schema, verified 2026-09-03) is `q`. This is the one
    real divergence from #159's original sketch worth a dedicated test."""
    mock = _mock_get(monkeypatch, _FakeResponse(200, {"items": [], "total": 0, "limit": 5, "offset": 0}))
    result = await afp_client.search_series(query="naruto", limit=5)
    assert result == {"items": [], "total": 0, "limit": 5, "offset": 0}
    _, kwargs = mock.call_args
    assert kwargs["params"] == {"q": "naruto", "limit": 5}


@pytest.mark.asyncio
async def test_get_series_by_id_or_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_get(monkeypatch, _FakeResponse(200, {"id": 42, "title": "Naruto: Shippuden"}))
    result = await afp_client.get_series("naruto-shippuuden")
    assert result["title"] == "Naruto: Shippuden"
    args, _ = mock.call_args
    assert args[0].endswith("/series/naruto-shippuuden")


@pytest.mark.asyncio
async def test_get_episodes_with_numeric_id_skips_series_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_get(monkeypatch, _FakeResponse(200, [{"id": 1, "episode_number": 1}]))
    result = await afp_client.get_episodes("42")
    assert result == [{"id": 1, "episode_number": 1}]
    # Only one call — no series lookup was needed to resolve a numeric id.
    assert mock.call_count == 1
    args, _ = mock.call_args
    assert args[0].endswith("/series/42/episodes")


@pytest.mark.asyncio
async def test_get_episodes_with_slug_resolves_id_first(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _FakeResponse(200, {"id": 42, "title": "Naruto: Shippuden"}),
        _FakeResponse(200, [{"id": 1, "episode_number": 1}]),
    ]
    mock = AsyncMock(side_effect=responses)
    monkeypatch.setattr(httpx.AsyncClient, "get", mock)

    result = await afp_client.get_episodes("naruto-shippuuden")

    assert result == [{"id": 1, "episode_number": 1}]
    assert mock.call_count == 2
    first_call_args, _ = mock.call_args_list[0]
    second_call_args, _ = mock.call_args_list[1]
    assert first_call_args[0].endswith("/series/naruto-shippuuden")
    assert second_call_args[0].endswith("/series/42/episodes")


@pytest.mark.asyncio
async def test_get_episode_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_get(monkeypatch, _FakeResponse(200, {"id": 501, "episode_number": 15}))
    result = await afp_client.get_episode(501)
    assert result["episode_number"] == 15
    args, _ = mock.call_args
    assert args[0].endswith("/episodes/501")


@pytest.mark.asyncio
async def test_get_license(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_get(
        monkeypatch,
        _FakeResponse(200, {"license": "CC BY-NC-SA 4.0", "attribution_notice": "..."}),
    )
    result = await afp_client.get_license()
    assert result["license"] == "CC BY-NC-SA 4.0"
    args, _ = mock.call_args
    assert args[0].endswith("/license")


@pytest.mark.asyncio
async def test_error_response_raises_afp_api_error_with_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get(monkeypatch, _FakeResponse(404, {"detail": "Series not found"}))
    with pytest.raises(afp_client.AFPAPIError) as exc_info:
        await afp_client.get_series("does-not-exist")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Series not found"


@pytest.mark.asyncio
async def test_error_response_falls_back_to_raw_text_when_body_not_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_get(monkeypatch, _FakeResponse(500, "internal server error"))
    with pytest.raises(afp_client.AFPAPIError) as exc_info:
        await afp_client.get_license()
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "internal server error"
