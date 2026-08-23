"""Real-Postgres tests for #3 — bulk approve/reject for both contributions
and series proposals. Same conventions as test_moderation.py (#13):
dedicated test series/users, prefixed test data, full cleanup.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from services.auth import Profile, login_or_create_user

TEST_SERIES_TITLE = "__test_3__series"
TEST_PROPOSAL_TITLE = "__test_3__proposed series"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_user(role: str = "contributor") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session,
                "github",
                Profile(provider_id=_unique_id(), email=None, display_name="tester", avatar_url=None),
            )
            if role != "contributor":
                await session.execute(
                    text("UPDATE users SET role = :role WHERE id = :id"),
                    {"role": role, "id": user.id},
                )
            return user.id


async def _delete_user(user_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


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
                        "(event_type IN ('contribution.submitted', 'contribution.approved', 'contribution.rejected')) "
                        "AND (payload->>'contribution_id')::int = ANY(:ids)"
                    ),
                    {"ids": contribution_ids},
                )


async def _cleanup_proposals_and_promoted_series() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            proposal_rows = (
                await session.execute(
                    text("SELECT id FROM series_proposals WHERE title LIKE :prefix"),
                    {"prefix": f"{TEST_PROPOSAL_TITLE}%"},
                )
            ).all()
            proposal_ids = [r.id for r in proposal_rows]
            await session.execute(text("DELETE FROM series_proposals WHERE title LIKE :prefix"), {"prefix": f"{TEST_PROPOSAL_TITLE}%"})
            await session.execute(text("DELETE FROM series WHERE title LIKE :prefix"), {"prefix": f"{TEST_PROPOSAL_TITLE}%"})
            if proposal_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "event_type IN ('series_proposal.submitted', 'series_proposal.approved', 'series_proposal.rejected') "
                        "AND (payload->>'series_proposal_id')::int = ANY(:ids)"
                    ),
                    {"ids": proposal_ids},
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


@pytest.fixture
async def contributor_id():
    user_id = await _make_user(role="contributor")
    yield user_id
    await _delete_user(user_id)


async def _submit_contribution(series_id: int, episode_number: int) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": series_id,
                "episode_number": episode_number,
                "proposed_status": "canon",
                "citation": {"description": "__test_3__ citation"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _submit_proposal(suffix: str) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": f"{TEST_PROPOSAL_TITLE}{suffix}",
                "justification": "__test_3__ justification",
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_bulk_approve_contributions_all_succeed(test_series_id: int, moderator_id: int) -> None:
    ids = [await _submit_contribution(test_series_id, n) for n in range(1, 4)]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        response = await client.post("/api/v1/contributions/bulk-approve", json={"ids": ids})

    assert response.status_code == 200, response.text
    results = {r["id"]: r for r in response.json()["results"]}
    assert all(results[i]["ok"] for i in ids)

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM episodes WHERE series_id = :sid"), {"sid": test_series_id}
            )
        ).scalar_one()
        assert count == 3


@pytest.mark.asyncio
async def test_bulk_approve_reports_per_id_failure_without_failing_the_rest(
    test_series_id: int, moderator_id: int
) -> None:
    good_ids = [await _submit_contribution(test_series_id, n) for n in range(10, 12)]
    already_approved_id = await _submit_contribution(test_series_id, 20)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        # Pre-approve one of them directly so the bulk call hits a real
        # "not pending" 409 for it.
        pre_approve = await client.post(f"/api/v1/contributions/{already_approved_id}/approve")
        assert pre_approve.status_code == 200, pre_approve.text

        response = await client.post(
            "/api/v1/contributions/bulk-approve",
            json={"ids": [*good_ids, already_approved_id, 999999999]},
        )

    assert response.status_code == 200, response.text
    results = {r["id"]: r for r in response.json()["results"]}
    assert all(results[i]["ok"] for i in good_ids)
    assert results[already_approved_id]["ok"] is False
    assert "not pending" in results[already_approved_id]["detail"]
    assert results[999999999]["ok"] is False
    assert "not found" in results[999999999]["detail"]

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM episodes WHERE series_id = :sid"), {"sid": test_series_id}
            )
        ).scalar_one()
        assert count == 3  # good_ids (2) + already_approved_id (1) — all really promoted


@pytest.mark.asyncio
async def test_bulk_reject_requires_review_note(test_series_id: int, moderator_id: int) -> None:
    ids = [await _submit_contribution(test_series_id, 30)]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        missing_note = await client.post("/api/v1/contributions/bulk-reject", json={"ids": ids})
        assert missing_note.status_code == 422

        empty_note = await client.post(
            "/api/v1/contributions/bulk-reject", json={"ids": ids, "review_note": ""}
        )
        assert empty_note.status_code == 422


@pytest.mark.asyncio
async def test_bulk_reject_applies_same_note_to_every_id(test_series_id: int, moderator_id: int) -> None:
    ids = [await _submit_contribution(test_series_id, n) for n in range(40, 43)]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        response = await client.post(
            "/api/v1/contributions/bulk-reject",
            json={"ids": ids, "review_note": "__test_3__ shared bulk rejection reason"},
        )

    assert response.status_code == 200, response.text
    assert all(r["ok"] for r in response.json()["results"])

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT review_note, review_status FROM contributions WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
        ).all()
        assert len(rows) == 3
        assert all(r.review_status == "rejected" for r in rows)
        assert all(r.review_note == "__test_3__ shared bulk rejection reason" for r in rows)


@pytest.mark.asyncio
async def test_bulk_moderation_requires_moderator_role(test_series_id: int, contributor_id: int) -> None:
    ids = [await _submit_contribution(test_series_id, 50)]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(contributor_id))
        approve_response = await client.post("/api/v1/contributions/bulk-approve", json={"ids": ids})
        assert approve_response.status_code == 403
        reject_response = await client.post(
            "/api/v1/contributions/bulk-reject", json={"ids": ids, "review_note": "x"}
        )
        assert reject_response.status_code == 403


@pytest.mark.asyncio
async def test_bulk_moderation_empty_ids_rejected(moderator_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        response = await client.post("/api/v1/contributions/bulk-approve", json={"ids": []})
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_approve_series_proposals(moderator_id: int) -> None:
    ids = [await _submit_proposal(f"-{n}") for n in range(1, 3)]
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
            response = await client.post("/api/v1/series-proposals/bulk-approve", json={"ids": ids})

        assert response.status_code == 200, response.text
        assert all(r["ok"] for r in response.json()["results"])

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM series WHERE title LIKE :prefix"),
                    {"prefix": f"{TEST_PROPOSAL_TITLE}%"},
                )
            ).scalar_one()
            assert count == 2
    finally:
        await _cleanup_proposals_and_promoted_series()


@pytest.mark.asyncio
async def test_bulk_reject_series_proposals_applies_same_note(moderator_id: int) -> None:
    ids = [await _submit_proposal(f"-reject-{n}") for n in range(1, 3)]
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
            response = await client.post(
                "/api/v1/series-proposals/bulk-reject",
                json={"ids": ids, "review_note": "__test_3__ shared proposal rejection"},
            )

        assert response.status_code == 200, response.text
        assert all(r["ok"] for r in response.json()["results"])

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    text("SELECT review_note FROM series_proposals WHERE id = ANY(:ids)"),
                    {"ids": ids},
                )
            ).all()
            assert all(r.review_note == "__test_3__ shared proposal rejection" for r in rows)
    finally:
        await _cleanup_proposals_and_promoted_series()
