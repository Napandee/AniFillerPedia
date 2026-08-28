"""Real-Postgres tests for #148 (suggest a synonym for an already-
catalogued series) — same convention as #12/#13's own test files:
exercise the real app against the real test-pg, prefix test data,
dedicated test series per test so cleanup is unambiguous.
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from services.auth import Profile, login_or_create_user

TEST_SERIES_TITLE = "__test_148__series"


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
            suggestion_ids = [
                r.id
                for r in (
                    await session.execute(
                        text("SELECT id FROM series_synonym_suggestions WHERE series_id = :sid"),
                        {"sid": series_id},
                    )
                ).all()
            ]
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if suggestion_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "event_type IN ('synonym_suggestion.submitted', 'synonym_suggestion.approved', "
                        "'synonym_suggestion.rejected') "
                        "AND (payload->>'synonym_suggestion_id')::int = ANY(:ids)"
                    ),
                    {"ids": suggestion_ids},
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


async def _submit_suggestion(series_id: int, synonym: str, **extra) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/synonym-suggestions",
            json={
                "series_id": series_id,
                "synonym": synonym,
                "license_accepted": True,
                **extra,
            },
        )
    assert response.status_code == 201, response.text
    return response.json()


# --- submission --------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_creates_pending_record(test_series_id: int) -> None:
    body = await _submit_suggestion(test_series_id, "__test_148__ Alt Title")
    assert body["review_status"] == "pending"
    assert body["series_id"] == test_series_id
    assert body["series_title"] == TEST_SERIES_TITLE
    assert body["synonym"] == "__test_148__ Alt Title"

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT review_status FROM series_synonym_suggestions WHERE id = :id"),
                {"id": body["id"]},
            )
        ).one()
        assert row.review_status == "pending"


@pytest.mark.asyncio
async def test_submit_requires_license_accepted(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/synonym-suggestions",
            json={
                "series_id": test_series_id,
                "synonym": "__test_148__ no license",
                "license_accepted": False,
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_against_nonexistent_series_is_404() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/synonym-suggestions",
            json={
                "series_id": 2147483647,
                "synonym": "__test_148__ ghost series",
                "license_accepted": True,
            },
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_submit_duplicate_of_existing_synonym_is_409(test_series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("INSERT INTO series_synonyms (series_id, synonym) VALUES (:sid, :syn)"),
                {"sid": test_series_id, "syn": "__test_148__ already known"},
            )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/synonym-suggestions",
            json={
                "series_id": test_series_id,
                "synonym": "__test_148__ already known",
                "license_accepted": True,
            },
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_submit_duplicate_pending_suggestion_is_409(test_series_id: int) -> None:
    first = await _submit_suggestion(test_series_id, "__test_148__ dup pending")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/synonym-suggestions",
            json={
                "series_id": test_series_id,
                "synonym": "__test_148__ dup pending",
                "license_accepted": True,
            },
        )
    assert response.status_code == 409
    assert response.json()["detail"]["existing_suggestion_id"] == first["id"]


@pytest.mark.asyncio
async def test_double_submit_race_is_guarded(test_series_id: int) -> None:
    """Same #20-style guard as contributions — two genuinely concurrent
    submissions for the identical (series_id, synonym) can't both create a
    pending row; the partial unique index (migrations/016) backstops the
    TOCTOU gap between the pre-check and the INSERT.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            client.post(
                "/api/v1/synonym-suggestions",
                json={
                    "series_id": test_series_id,
                    "synonym": "__test_148__ race",
                    "license_accepted": True,
                },
            ),
            client.post(
                "/api/v1/synonym-suggestions",
                json={
                    "series_id": test_series_id,
                    "synonym": "__test_148__ race",
                    "license_accepted": True,
                },
            ),
            return_exceptions=True,
        )

    status_codes = sorted(
        r.status_code if not isinstance(r, BaseException) else -1 for r in responses
    )
    assert status_codes == [201, 409], status_codes

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM series_synonym_suggestions "
                    "WHERE series_id = :sid AND synonym = :syn"
                ),
                {"sid": test_series_id, "syn": "__test_148__ race"},
            )
        ).scalar_one()
        assert count == 1


# --- moderation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_non_moderator_forbidden_from_queue_and_actions(
    test_series_id: int, contributor_id: int
) -> None:
    suggestion = await _submit_suggestion(test_series_id, "__test_148__ forbidden check")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(contributor_id))

        queue_response = await client.get("/api/v1/synonym-suggestions")
        assert queue_response.status_code == 403

        approve_response = await client.post(f"/api/v1/synonym-suggestions/{suggestion['id']}/approve")
        assert approve_response.status_code == 403


@pytest.mark.asyncio
async def test_approve_inserts_into_series_synonyms(
    test_series_id: int, moderator_id: int
) -> None:
    suggestion = await _submit_suggestion(test_series_id, "__test_148__ approved synonym")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        queue_response = await client.get("/api/v1/synonym-suggestions")
        assert queue_response.status_code == 200
        assert suggestion["id"] in {s["id"] for s in queue_response.json()}

        approve_response = await client.post(f"/api/v1/synonym-suggestions/{suggestion['id']}/approve")
        assert approve_response.status_code == 200, approve_response.text
        assert approve_response.json()["review_status"] == "approved"

    async with async_session_factory() as session:
        synonym_row = (
            await session.execute(
                text(
                    "SELECT 1 FROM series_synonyms WHERE series_id = :sid AND synonym = :syn"
                ),
                {"sid": test_series_id, "syn": "__test_148__ approved synonym"},
            )
        ).first()
        assert synonym_row is not None

        outbox_row = (
            await session.execute(
                text(
                    "SELECT id FROM outbox_events WHERE event_type = 'synonym_suggestion.approved' "
                    "AND (payload->>'synonym_suggestion_id')::int = :sid"
                ),
                {"sid": suggestion["id"]},
            )
        ).first()
        assert outbox_row is not None


@pytest.mark.asyncio
async def test_reject_requires_review_note_and_does_not_insert(
    test_series_id: int, moderator_id: int
) -> None:
    suggestion = await _submit_suggestion(test_series_id, "__test_148__ rejected synonym")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        missing_note = await client.post(
            f"/api/v1/synonym-suggestions/{suggestion['id']}/reject", json={}
        )
        assert missing_note.status_code == 422

        rejected = await client.post(
            f"/api/v1/synonym-suggestions/{suggestion['id']}/reject",
            json={"review_note": "__test_148__ not a real alternate title"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["review_status"] == "rejected"

    async with async_session_factory() as session:
        synonym_row = (
            await session.execute(
                text(
                    "SELECT 1 FROM series_synonyms WHERE series_id = :sid AND synonym = :syn"
                ),
                {"sid": test_series_id, "syn": "__test_148__ rejected synonym"},
            )
        ).first()
        assert synonym_row is None  # a rejected suggestion must never be promoted


@pytest.mark.asyncio
async def test_approve_already_resolved_suggestion_is_409(
    test_series_id: int, moderator_id: int
) -> None:
    suggestion = await _submit_suggestion(test_series_id, "__test_148__ double approve")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        first = await client.post(f"/api/v1/synonym-suggestions/{suggestion['id']}/approve")
        assert first.status_code == 200
        second = await client.post(f"/api/v1/synonym-suggestions/{suggestion['id']}/approve")
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_approve_nonexistent_suggestion_is_404(moderator_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        response = await client.post("/api/v1/synonym-suggestions/2147483647/approve")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bulk_approve_and_bulk_reject(test_series_id: int, moderator_id: int) -> None:
    approve_target = await _submit_suggestion(test_series_id, "__test_148__ bulk approve me")
    reject_target = await _submit_suggestion(test_series_id, "__test_148__ bulk reject me")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        approve_response = await client.post(
            "/api/v1/synonym-suggestions/bulk-approve", json={"ids": [approve_target["id"]]}
        )
        assert approve_response.status_code == 200, approve_response.text
        assert approve_response.json()["results"] == [{"id": approve_target["id"], "ok": True, "detail": None}]

        reject_response = await client.post(
            "/api/v1/synonym-suggestions/bulk-reject",
            json={"ids": [reject_target["id"]], "review_note": "__test_148__ bulk rejected"},
        )
        assert reject_response.status_code == 200, reject_response.text
        assert reject_response.json()["results"] == [{"id": reject_target["id"], "ok": True, "detail": None}]

    async with async_session_factory() as session:
        approved_row = (
            await session.execute(
                text("SELECT 1 FROM series_synonyms WHERE series_id = :sid AND synonym = :syn"),
                {"sid": test_series_id, "syn": "__test_148__ bulk approve me"},
            )
        ).first()
        assert approved_row is not None

        rejected_row = (
            await session.execute(
                text("SELECT 1 FROM series_synonyms WHERE series_id = :sid AND synonym = :syn"),
                {"sid": test_series_id, "syn": "__test_148__ bulk reject me"},
            )
        ).first()
        assert rejected_row is None


@pytest.mark.asyncio
async def test_my_synonym_suggestions_requires_login() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/synonym-suggestions/mine")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_my_synonym_suggestions_lists_only_own(
    test_series_id: int, contributor_id: int
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(contributor_id))
        submit_response = await client.post(
            "/api/v1/synonym-suggestions",
            json={
                "series_id": test_series_id,
                "synonym": "__test_148__ mine",
                "license_accepted": True,
            },
        )
        assert submit_response.status_code == 201
        suggestion_id = submit_response.json()["id"]

        mine_response = await client.get("/api/v1/synonym-suggestions/mine")
        assert mine_response.status_code == 200
        assert suggestion_id in {s["id"] for s in mine_response.json()}
