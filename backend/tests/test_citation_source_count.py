"""Real-Postgres tests for #204 (source_count exposed on the live
submission API) and #205 (the shared repositories/citations.py::
get_or_create consistency check both write paths now use). Same
convention as the rest of this suite: real DB, __test_204__-prefixed test
data, dedicated series per test.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from repositories.citations import SourceCountConflict, get_or_create
from services.auth import Profile, login_or_create_user

TEST_SERIES_TITLE = "__test_204__series"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_user(role: str = "moderator") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session,
                "github",
                Profile(provider_id=_unique_id(), email=None, display_name="tester", avatar_url=None),
            )
            if role != "contributor":
                await session.execute(
                    text("UPDATE users SET role = :role WHERE id = :id"), {"role": role, "id": user.id}
                )
            return user.id


async def _delete_user(user_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def _make_test_series(title: str = TEST_SERIES_TITLE) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text("INSERT INTO series (title, provenance) VALUES (:title, 'community') RETURNING id"),
                {"title": title},
            )
            return result.scalar_one()


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            episode_rows = (
                await session.execute(text("SELECT id FROM episodes WHERE series_id = :sid"), {"sid": series_id})
            ).all()
            contribution_rows = (
                await session.execute(
                    text("SELECT id, citation_id FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).all()
            contribution_ids = [r.id for r in contribution_rows]
            citation_ids = [r.citation_id for r in contribution_rows]
            if episode_rows:
                await session.execute(text("DELETE FROM episodes WHERE series_id = :sid"), {"sid": series_id})
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if citation_ids:
                await session.execute(text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids})
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "event_type IN ('contribution.submitted', 'contribution.approved') "
                        "AND (payload->>'contribution_id')::int = ANY(:ids)"
                    ),
                    {"ids": contribution_ids},
                )


@pytest.fixture
async def test_series_id():
    series_id = await _make_test_series()
    yield series_id
    await _cleanup_series(series_id)


@pytest.fixture
async def moderator_id():
    user_id = await _make_user(role="moderator")
    yield user_id
    await _delete_user(user_id)


@pytest.mark.asyncio
async def test_submission_source_count_defaults_to_one(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 1,
                "proposed_status": "canon",
                "citation": {"description": "__test_204__ single-source citation"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["citation"]["source_count"] == 1


@pytest.mark.asyncio
async def test_submission_can_declare_multiple_corroborating_sources(test_series_id: int) -> None:
    """#204's core acceptance criterion: a real contributor genuinely
    cross-referencing multiple independent sources can express that via
    the live API, not just via bootstrap tooling.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 2,
                "proposed_status": "filler",
                "citation": {
                    "description": "__test_204__ cross-referenced against 3 independent guides",
                    "source_count": 3,
                },
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["citation"]["source_count"] == 3


@pytest.mark.asyncio
async def test_corroboration_badge_data_survives_moderator_approval(
    test_series_id: int, moderator_id: int
) -> None:
    """#204's other acceptance criterion: the corroboration badge renders
    correctly for a submission made through the live API, not just for
    bootstrap-loaded data — verified end to end via the real approval flow
    into GET /series/{id}/episodes, the exact endpoint the badge reads.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submit_response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 3,
                "proposed_status": "canon",
                "citation": {
                    "description": "__test_204__ triple-corroborated",
                    "source_count": 3,
                },
                "license_accepted": True,
            },
        )
        assert submit_response.status_code == 201, submit_response.text
        contribution_id = submit_response.json()["id"]

        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        approve_response = await client.post(f"/api/v1/contributions/{contribution_id}/approve")
        assert approve_response.status_code == 200, approve_response.text

        episodes_response = await client.get(f"/api/v1/series/{test_series_id}/episodes")
    assert episodes_response.status_code == 200, episodes_response.text
    episode = next(e for e in episodes_response.json() if e["episode_number"] == 3)
    assert episode["citation"]["source_count"] == 3


@pytest.mark.asyncio
async def test_conflicting_source_count_rejected_via_single_submission_api(test_series_id: int) -> None:
    """#205: the shared consistency check applied to the single-episode
    submission path — a second submission citing the EXACT same source
    combo (description/url/methodology_note) for this series with a
    DIFFERENT source_count is rejected, rather than silently creating a
    second, inconsistent citation row for what's supposed to be the same
    source combination.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 4,
                "proposed_status": "canon",
                "citation": {
                    "url": "https://example.com/__test_205__guide",
                    "description": "__test_205__ shared combo",
                    "source_count": 2,
                },
                "license_accepted": True,
            },
        )
        assert first.status_code == 201, first.text

        conflicting = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 5,
                "proposed_status": "canon",
                "citation": {
                    "url": "https://example.com/__test_205__guide",
                    "description": "__test_205__ shared combo",
                    "source_count": 5,
                },
                "license_accepted": True,
            },
        )
    assert conflicting.status_code == 422, conflicting.text


@pytest.mark.asyncio
async def test_matching_source_count_reuses_existing_citation_row(test_series_id: int) -> None:
    """The non-conflict half of #205's rule: the exact same combo with an
    AGREEING source_count is reused (never duplicated), same as
    load_episodes.py's own citation-merging behavior.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 6,
                "proposed_status": "canon",
                "citation": {
                    "description": "__test_205__ reused combo",
                    "source_count": 2,
                },
                "license_accepted": True,
            },
        )
        assert first.status_code == 201, first.text
        first_citation_id = first.json()["citation"]["id"]

        second = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 7,
                "proposed_status": "canon",
                "citation": {
                    "description": "__test_205__ reused combo",
                    "source_count": 2,
                },
                "license_accepted": True,
            },
        )
        assert second.status_code == 201, second.text
    assert second.json()["citation"]["id"] == first_citation_id


@pytest.mark.asyncio
async def test_conflicting_source_count_rejected_via_bulk_submission_api(test_series_id: int) -> None:
    """#205's shared check reused by the BULK path too — same rule
    regardless of which write path attempts it. The bulk endpoint requires
    authentication (unlike the single-episode path), so this submits an
    initial single-episode citation, then a bulk call citing the identical
    combo with a conflicting source_count.
    """
    user_id = await _make_user(role="contributor")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/api/v1/contributions",
                json={
                    "series_id": test_series_id,
                    "episode_number": 8,
                    "proposed_status": "canon",
                    "citation": {
                        "description": "__test_205__ bulk-vs-single combo",
                        "source_count": 1,
                    },
                    "license_accepted": True,
                },
            )
            assert first.status_code == 201, first.text

            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
            bulk = await client.post(
                f"/api/v1/series/{test_series_id}/contributions/bulk",
                json={
                    "canon_ranges": "9",
                    "citation": {
                        "description": "__test_205__ bulk-vs-single combo",
                        "source_count": 4,
                    },
                    "license_accepted": True,
                },
            )
        assert bulk.status_code == 422, bulk.text
    finally:
        await _delete_user(user_id)


@pytest.mark.asyncio
async def test_get_or_create_repository_function_conflict_and_reuse(test_series_id: int) -> None:
    """Direct repository-level test of #205's shared get_or_create() —
    the lowest-level unit both write paths call through.
    """
    async with async_session_factory() as session:
        async with session.begin():
            # A contribution row must exist citing the citation for
            # find_matching_for_series's join to see it (citations aren't
            # directly linked to a series otherwise) — inserted directly
            # to isolate this test from the submission API entirely.
            first_citation = await get_or_create(
                session,
                series_id=test_series_id,
                url=None,
                description="__test_205__ repo-level combo",
                submitted_by=None,
                methodology_note=None,
                source_count=2,
            )
            await session.execute(
                text(
                    "INSERT INTO contributions "
                    "(series_id, episode_number, proposed_status, citation_id, license_accepted) "
                    "VALUES (:sid, 10, 'canon', :cid, true)"
                ),
                {"sid": test_series_id, "cid": first_citation.id},
            )

    # Matching source_count -> reused, not duplicated.
    async with async_session_factory() as session:
        async with session.begin():
            reused = await get_or_create(
                session,
                series_id=test_series_id,
                url=None,
                description="__test_205__ repo-level combo",
                submitted_by=None,
                methodology_note=None,
                source_count=2,
            )
    assert reused.id == first_citation.id

    # Conflicting source_count -> raises, never silently written.
    with pytest.raises(SourceCountConflict) as exc_info:
        async with async_session_factory() as session:
            async with session.begin():
                await get_or_create(
                    session,
                    series_id=test_series_id,
                    url=None,
                    description="__test_205__ repo-level combo",
                    submitted_by=None,
                    methodology_note=None,
                    source_count=9,
                )
    assert exc_info.value.existing_source_count == 2
    assert exc_info.value.proposed_source_count == 9
