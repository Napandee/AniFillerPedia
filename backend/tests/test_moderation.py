"""Real-Postgres tests for #13 (moderator approve/reject) — same convention
as #12's tests/test_contributions.py: exercise against a real DB, test data
prefixed __test_13__, dedicated test series per test so cleanup is
unambiguous.
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

TEST_SERIES_TITLE = "__test_13__series"


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
            # episodes.citation_id and approved_contribution_id both have
            # plain FKs (no CASCADE) — capture ids first, delete episodes
            # explicitly, then the series (CASCADEs to contributions), then
            # the now-unreferenced citations and outbox rows. Same ordering
            # lesson #12's tests already learned the hard way.
            episode_rows = (
                await session.execute(
                    text("SELECT id FROM episodes WHERE series_id = :sid"), {"sid": series_id}
                )
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
                await session.execute(
                    text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids}
                )
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "(event_type IN ('contribution.submitted', 'contribution.approved', 'contribution.rejected')) "
                        "AND (payload->>'contribution_id')::int = ANY(:ids)"
                    ),
                    {"ids": contribution_ids},
                )


async def _cleanup_series_proposal(proposal_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM series_proposals WHERE id = :id"), {"id": proposal_id})
            await session.execute(
                text(
                    "DELETE FROM outbox_events WHERE "
                    "event_type IN ('series_proposal.submitted', 'series_proposal.approved', 'series_proposal.rejected') "
                    "AND (payload->>'series_proposal_id')::int = :id"
                ),
                {"id": proposal_id},
            )


async def _cleanup_promoted_series(title: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM series WHERE title = :title"), {"title": title})


async def _cleanup_promoted_series_with_contributions(title: str) -> None:
    """#85: same as _cleanup_promoted_series, but also tears down whatever
    contributions/citations/outbox rows an approval with attached
    episode_data created for the promoted series — series itself CASCADEs
    into contributions, but citations and outbox rows don't cascade from
    either side (same lesson _cleanup_series above already learned).
    """
    async with async_session_factory() as session:
        async with session.begin():
            series_row = (
                await session.execute(text("SELECT id FROM series WHERE title = :title"), {"title": title})
            ).first()
            if series_row is None:
                return
            series_id = series_row.id
            contribution_rows = (
                await session.execute(
                    text("SELECT id, citation_id FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).all()
            contribution_ids = [r.id for r in contribution_rows]
            citation_ids = [r.citation_id for r in contribution_rows]

            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if citation_ids:
                await session.execute(text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids})
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "event_type = 'contribution.submitted' "
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
                "citation": {"description": "__test_13__ citation"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_non_moderator_forbidden_from_queue_and_actions(
    test_series_id: int, contributor_id: int
) -> None:
    contribution_id = await _submit_contribution(test_series_id, 1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(contributor_id))

        queue_response = await client.get("/api/v1/contributions")
        assert queue_response.status_code == 403

        approve_response = await client.post(f"/api/v1/contributions/{contribution_id}/approve")
        assert approve_response.status_code == 403


@pytest.mark.asyncio
async def test_approve_promotes_pending_contribution_into_episodes(
    test_series_id: int, moderator_id: int
) -> None:
    contribution_id = await _submit_contribution(test_series_id, 2)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        queue_response = await client.get("/api/v1/contributions")
        assert queue_response.status_code == 200
        assert contribution_id in {c["id"] for c in queue_response.json()}

        approve_response = await client.post(f"/api/v1/contributions/{contribution_id}/approve")
        assert approve_response.status_code == 200, approve_response.text
        body = approve_response.json()
        assert body["review_status"] == "approved"
        assert body["resolution_method"] == "moderator"

    async with async_session_factory() as session:
        episode_row = (
            await session.execute(
                text(
                    "SELECT status, approved_contribution_id FROM episodes "
                    "WHERE series_id = :sid AND episode_number = 2"
                ),
                {"sid": test_series_id},
            )
        ).one()
        assert episode_row.status == "canon"
        assert episode_row.approved_contribution_id == contribution_id

        outbox_row = (
            await session.execute(
                text(
                    "SELECT id FROM outbox_events WHERE event_type = 'contribution.approved' "
                    "AND (payload->>'contribution_id')::int = :cid"
                ),
                {"cid": contribution_id},
            )
        ).first()
        assert outbox_row is not None


@pytest.mark.asyncio
async def test_reject_requires_review_note(test_series_id: int, moderator_id: int) -> None:
    contribution_id = await _submit_contribution(test_series_id, 3)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        missing_note = await client.post(f"/api/v1/contributions/{contribution_id}/reject", json={})
        assert missing_note.status_code == 422

        empty_note = await client.post(
            f"/api/v1/contributions/{contribution_id}/reject", json={"review_note": ""}
        )
        assert empty_note.status_code == 422

        rejected = await client.post(
            f"/api/v1/contributions/{contribution_id}/reject",
            json={"review_note": "__test_13__ not enough evidence"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["review_status"] == "rejected"
        assert rejected.json()["review_note"] == "__test_13__ not enough evidence"

    async with async_session_factory() as session:
        episode_row = (
            await session.execute(
                text("SELECT id FROM episodes WHERE series_id = :sid AND episode_number = 3"),
                {"sid": test_series_id},
            )
        ).first()
        assert episode_row is None  # a rejected contribution must never promote


@pytest.mark.asyncio
async def test_double_approval_race_is_guarded(test_series_id: int, moderator_id: int) -> None:
    """Concurrent approve calls on the same contribution must never both
    succeed — mirrors #9's test_concurrent_pollers_never_double_handle,
    exercising the guarded UPDATE ... WHERE review_status = 'pending'
    pattern instead of FOR UPDATE SKIP LOCKED.
    """
    contribution_id = await _submit_contribution(test_series_id, 4)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        responses = await asyncio.gather(
            client.post(f"/api/v1/contributions/{contribution_id}/approve"),
            client.post(f"/api/v1/contributions/{contribution_id}/approve"),
            return_exceptions=True,
        )

    status_codes = sorted(
        r.status_code if not isinstance(r, BaseException) else -1 for r in responses
    )
    assert status_codes == [200, 409], status_codes

    async with async_session_factory() as session:
        outbox_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_events WHERE event_type = 'contribution.approved' "
                    "AND (payload->>'contribution_id')::int = :cid"
                ),
                {"cid": contribution_id},
            )
        ).scalar_one()
        assert outbox_count == 1  # never double-written


@pytest.mark.asyncio
async def test_approve_series_proposal_promotes_into_series(moderator_id: int) -> None:
    title = "__test_13__promoted series"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submit_response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": title,
                "justification": "__test_13__ justification",
                "license_accepted": True,
            },
        )
        assert submit_response.status_code == 201
        proposal_id = submit_response.json()["id"]

        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        queue_response = await client.get("/api/v1/series-proposals")
        assert queue_response.status_code == 200
        assert proposal_id in {p["id"] for p in queue_response.json()}

        approve_response = await client.post(f"/api/v1/series-proposals/{proposal_id}/approve")
        assert approve_response.status_code == 200, approve_response.text
        assert approve_response.json()["review_status"] == "approved"

    try:
        async with async_session_factory() as session:
            series_row = (
                await session.execute(
                    text("SELECT provenance FROM series WHERE title = :title"), {"title": title}
                )
            ).first()
            assert series_row is not None
            assert series_row.provenance == "community"

            outbox_row = (
                await session.execute(
                    text(
                        "SELECT id FROM outbox_events WHERE event_type = 'series_proposal.approved' "
                        "AND (payload->>'series_proposal_id')::int = :pid"
                    ),
                    {"pid": proposal_id},
                )
            ).first()
            assert outbox_row is not None
    finally:
        await _cleanup_series_proposal(proposal_id)
        await _cleanup_promoted_series(title)


@pytest.mark.asyncio
async def test_reject_series_proposal_requires_review_note(moderator_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submit_response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": "__test_13__rejected series",
                "justification": "__test_13__ justification",
                "license_accepted": True,
            },
        )
        assert submit_response.status_code == 201
        proposal_id = submit_response.json()["id"]

        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))

        missing_note = await client.post(f"/api/v1/series-proposals/{proposal_id}/reject", json={})
        assert missing_note.status_code == 422

        rejected = await client.post(
            f"/api/v1/series-proposals/{proposal_id}/reject",
            json={"review_note": "__test_13__ duplicate of an existing series"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["review_status"] == "rejected"

    await _cleanup_series_proposal(proposal_id)


@pytest.mark.asyncio
async def test_approve_nonexistent_contribution_is_404(moderator_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        response = await client.post("/api/v1/contributions/2147483647/approve")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_already_resolved_contribution_is_409(
    test_series_id: int, moderator_id: int
) -> None:
    contribution_id = await _submit_contribution(test_series_id, 5)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        first = await client.post(f"/api/v1/contributions/{contribution_id}/approve")
        assert first.status_code == 200
        second = await client.post(f"/api/v1/contributions/{contribution_id}/approve")
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_submit_series_proposal_with_malformed_episode_data_returns_422() -> None:
    """#85: bad ranges are caught at submission time, not deferred to
    approval — same 422 shape #80's bulk endpoint already uses.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": "__test_85__malformed episode data",
                "justification": "__test_85__ justification",
                "license_accepted": True,
                "episode_data": {
                    "canon_ranges": "not-a-range",
                    "citation": {"description": "__test_85__ citation"},
                },
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_approve_series_proposal_with_episode_data_creates_bulk_contributions(
    moderator_id: int,
) -> None:
    """#85: a proposal submitted with attached episode-range data creates
    the series AND the bulk contributions in one approval step, reusing
    #80's own validation/creation core.
    """
    title = "__test_85__series with episode data"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submit_response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": title,
                "justification": "__test_85__ justification",
                "license_accepted": True,
                "episode_data": {
                    "canon_ranges": "1-3",
                    "filler_ranges": "4",
                    "citation": {"description": "__test_85__ citation"},
                },
            },
        )
        assert submit_response.status_code == 201, submit_response.text
        submitted = submit_response.json()
        proposal_id = submitted["id"]
        assert submitted["episode_data"]["declared_count"] == 4

        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        approve_response = await client.post(f"/api/v1/series-proposals/{proposal_id}/approve")
        assert approve_response.status_code == 200, approve_response.text
        approve_body = approve_response.json()
        assert approve_body["review_status"] == "approved"
        assert approve_body["episode_contributions_created"] == 4

    try:
        async with async_session_factory() as session:
            series_row = (
                await session.execute(text("SELECT id FROM series WHERE title = :title"), {"title": title})
            ).first()
            assert series_row is not None
            series_id = series_row.id

            contribution_rows = (
                await session.execute(
                    text(
                        "SELECT episode_number, proposed_status FROM contributions "
                        "WHERE series_id = :sid ORDER BY episode_number"
                    ),
                    {"sid": series_id},
                )
            ).all()
            assert [(r.episode_number, r.proposed_status) for r in contribution_rows] == [
                (1, "canon"),
                (2, "canon"),
                (3, "canon"),
                (4, "filler"),
            ]
    finally:
        await _cleanup_series_proposal(proposal_id)
        await _cleanup_promoted_series_with_contributions(title)


@pytest.mark.asyncio
async def test_reject_series_proposal_with_episode_data_creates_nothing(moderator_id: int) -> None:
    """#85: rejecting a proposal with attached episode data discards it —
    nothing orphaned, since it never became a real series/citation/
    contribution in the first place (it just sits as JSON on the now-
    rejected proposal row, same as any other rejected proposal field).
    """
    title = "__test_85__rejected series with episode data"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submit_response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": title,
                "justification": "__test_85__ justification",
                "license_accepted": True,
                "episode_data": {
                    "canon_ranges": "1-5",
                    "citation": {"description": "__test_85__ citation"},
                },
            },
        )
        assert submit_response.status_code == 201
        proposal_id = submit_response.json()["id"]

        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        rejected = await client.post(
            f"/api/v1/series-proposals/{proposal_id}/reject",
            json={"review_note": "__test_85__ not needed"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["review_status"] == "rejected"
        assert rejected.json()["episode_contributions_created"] is None

    async with async_session_factory() as session:
        series_row = (
            await session.execute(text("SELECT id FROM series WHERE title = :title"), {"title": title})
        ).first()
        assert series_row is None

    await _cleanup_series_proposal(proposal_id)
