"""Real-Postgres tests for #184 — stored XSS via unvalidated citation URL
scheme. Same convention as every other test file in this suite: exercise
against a real DB, not mocks; test data prefixed __test_184__, a dedicated
test series per test so cleanup is unambiguous.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.db import async_session_factory
from main import app

TEST_SERIES_TITLE = "__test_184__series"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_test_series() -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text("INSERT INTO series (title, provenance) VALUES (:title, 'community') RETURNING id"),
                {"title": TEST_SERIES_TITLE},
            )
            return result.scalar_one()


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            rows = (
                await session.execute(
                    text("SELECT id, citation_id FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).all()
            contribution_ids = [r.id for r in rows]
            citation_ids = [r.citation_id for r in rows]
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if citation_ids:
                await session.execute(text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids})
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE event_type = 'contribution.submitted' "
                        "AND (payload->>'contribution_id')::int = ANY(:ids)"
                    ),
                    {"ids": contribution_ids},
                )


@pytest.fixture
async def test_series_id():
    series_id = await _make_test_series()
    yield series_id
    await _cleanup_series(series_id)


async def _submit(series_id: int, episode_number: int, url: str) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/v1/contributions",
            json={
                "series_id": series_id,
                "episode_number": episode_number,
                "proposed_status": "canon",
                "citation": {"url": url, "description": "__test_184__ citation"},
                "license_accepted": True,
            },
        )


@pytest.mark.asyncio
async def test_javascript_scheme_citation_url_rejected_with_422(test_series_id: int) -> None:
    response = await _submit(test_series_id, 1, "javascript:alert(document.cookie)")
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_data_scheme_citation_url_rejected_with_422(test_series_id: int) -> None:
    response = await _submit(test_series_id, 2, "data:text/html,<script>alert(1)</script>")
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_http_and_https_citation_urls_accepted(test_series_id: int) -> None:
    http_response = await _submit(test_series_id, 3, "http://example.com/guide")
    assert http_response.status_code == 201, http_response.text

    https_response = await _submit(test_series_id, 4, "https://example.com/guide")
    assert https_response.status_code == 201, https_response.text


@pytest.mark.asyncio
async def test_citation_url_scheme_check_is_case_insensitive(test_series_id: int) -> None:
    # A URL's scheme is conventionally lowercase but not enforced as such
    # by any spec — the validator (and the DB CHECK constraint added in
    # the same migration) must not reject a technically-valid uppercase
    # scheme just because it's unusual.
    response = await _submit(test_series_id, 5, "HTTPS://Example.com/Guide")
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_citation_url_over_max_length_rejected_with_422(test_series_id: int) -> None:
    # #184: url gets the same max_length cap already used on description/
    # methodology_note (3000, #140) — well beyond any real citation URL,
    # but bounds the same storage-bloat vector.
    absurdly_long_url = "https://example.com/" + ("a" * 3000)
    response = await _submit(test_series_id, 6, absurdly_long_url)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_citations_url_scheme_db_check_constraint_rejects_bypassing_pydantic() -> None:
    """#184's defense-in-depth layer: even a write path that bypasses the
    Pydantic validator entirely (a raw SQL insert, matching what a bug in
    some other future validator might produce) is blocked at the database
    level by the citations_url_scheme_check CHECK constraint added in the
    same migration as the Pydantic-layer fix.
    """
    with pytest.raises(IntegrityError):
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO citations (url, description, source_count) "
                        "VALUES (:url, :description, 1)"
                    ),
                    {
                        "url": "javascript:alert(1)",
                        "description": "__test_184__ raw SQL bypass attempt",
                    },
                )


@pytest.mark.asyncio
async def test_citations_url_scheme_db_check_constraint_allows_null_url() -> None:
    # citations.url stays nullable (a source may be a book/guide with no
    # URL at all, per schema.sql's own header comment) — the CHECK
    # constraint must not accidentally start rejecting NULL.
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO citations (url, description, source_count) "
                    "VALUES (NULL, :description, 1) RETURNING id"
                ),
                {"description": "__test_184__ no-url citation"},
            )
            citation_id = result.scalar_one()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM citations WHERE id = :id"), {"id": citation_id})


@pytest.mark.asyncio
async def test_no_already_stored_non_http_url_exists() -> None:
    """#184's own acceptance criterion: audit existing data for any
    already-stored non-http(s) URL. Real, permanent regression test — not
    just a one-time manual check — since the CHECK constraint alone
    doesn't cover any citation row written before this migration existed.
    """
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT id, url FROM citations WHERE url IS NOT NULL AND url !~* '^https?://'")
            )
        ).all()
        assert rows == [], f"found non-http(s) citation URLs: {rows}"
