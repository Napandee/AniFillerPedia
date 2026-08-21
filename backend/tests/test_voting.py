"""Real-Postgres tests for #14 (community trust-weighted voting) — same
convention as #13's test_moderation.py: exercise against a real DB, test
data prefixed __test_14__, dedicated test series per test so cleanup is
unambiguous.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from services.auth import Profile, login_or_create_user

TEST_SERIES_TITLE = "__test_14__series"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_user(role: str = "contributor") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session,
                "github",
                Profile(provider_id=_unique_id(), email=None, display_name="voter", avatar_url=None),
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


async def _grant_trust(user_id: int, series_id: int, *, approved: int = 0, rejected: int = 0) -> None:
    """Seeds resolved contributions directly (bypassing the real
    submit->review flow — not what's under test here) so a voter has a
    known trust_score = approved - rejected * 2 at vote time. Uses episode
    numbers far outside any real test's range to avoid colliding with the
    one-pending-per-episode partial unique index (moot anyway since these
    are inserted already-resolved, never pending).
    """
    async with async_session_factory() as session:
        async with session.begin():
            for i in range(approved):
                citation_id = (
                    await session.execute(
                        text("INSERT INTO citations (description, submitted_by) VALUES (:d, :u) RETURNING id"),
                        {"d": "__test_14__ seed citation", "u": user_id},
                    )
                ).scalar_one()
                await session.execute(
                    text(
                        """
                        INSERT INTO contributions
                            (series_id, episode_number, proposed_status, citation_id, submitted_by,
                             license_accepted, review_status, resolution_method, reviewed_at)
                        VALUES (:sid, :ep, 'canon', :cid, :uid, true, 'approved', 'moderator', now())
                        """
                    ),
                    {"sid": series_id, "ep": 9000 + i, "cid": citation_id, "uid": user_id},
                )
            for i in range(rejected):
                citation_id = (
                    await session.execute(
                        text("INSERT INTO citations (description, submitted_by) VALUES (:d, :u) RETURNING id"),
                        {"d": "__test_14__ seed citation", "u": user_id},
                    )
                ).scalar_one()
                await session.execute(
                    text(
                        """
                        INSERT INTO contributions
                            (series_id, episode_number, proposed_status, citation_id, submitted_by,
                             license_accepted, review_status, resolution_method, reviewed_at, review_note)
                        VALUES (:sid, :ep, 'canon', :cid, :uid, true, 'rejected', 'moderator', now(), 'seed')
                        """
                    ),
                    {"sid": series_id, "ep": 9500 + i, "cid": citation_id, "uid": user_id},
                )


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            episode_rows = (
                await session.execute(text("SELECT id FROM episodes WHERE series_id = :sid"), {"sid": series_id})
            ).all()
            contribution_rows = (
                await session.execute(
                    text("SELECT id, citation_id FROM contributions WHERE series_id = :sid"), {"sid": series_id}
                )
            ).all()
            contribution_ids = [r.id for r in contribution_rows]
            citation_ids = [r.citation_id for r in contribution_rows]

            if episode_rows:
                await session.execute(text("DELETE FROM episodes WHERE series_id = :sid"), {"sid": series_id})
            # contribution_votes CASCADEs from contributions, which CASCADEs from series.
            await session.execute(text("DELETE FROM series WHERE id = :id"), {"id": series_id})
            if citation_ids:
                await session.execute(text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids})
            if contribution_ids:
                await session.execute(
                    text(
                        "DELETE FROM outbox_events WHERE "
                        "event_type IN ('contribution.submitted', 'contribution.approved', 'contribution.rejected') "
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
async def submitter_id():
    user_id = await _make_user()
    yield user_id
    await _delete_user(user_id)


@pytest.fixture
async def moderator_id():
    user_id = await _make_user(role="moderator")
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
                "citation": {"description": "__test_14__ citation"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _submit_contribution_as(user_id: int, series_id: int, episode_number: int) -> int:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": series_id,
                "episode_number": episode_number,
                "proposed_status": "canon",
                "citation": {"description": "__test_14__ citation"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _vote_as(user_id: int, contribution_id: int, vote: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
        return await client.post(f"/api/v1/contributions/{contribution_id}/vote", json={"vote": vote})


@pytest.mark.asyncio
async def test_vote_requires_authentication(test_series_id: int) -> None:
    contribution_id = await _submit_contribution(test_series_id, 1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/v1/contributions/{contribution_id}/vote", json={"vote": "endorse"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_self_vote_forbidden(test_series_id: int, submitter_id: int) -> None:
    contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 2)
    response = await _vote_as(submitter_id, contribution_id, "endorse")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_vote_forbidden(test_series_id: int, submitter_id: int) -> None:
    contribution_id = await _submit_contribution(test_series_id, 3)
    first = await _vote_as(submitter_id, contribution_id, "endorse")
    assert first.status_code == 200, first.text
    second = await _vote_as(submitter_id, contribution_id, "dispute")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_vote_on_nonexistent_contribution_is_404(submitter_id: int) -> None:
    response = await _vote_as(submitter_id, 2147483647, "endorse")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_vote_on_resolved_contribution_is_409(
    test_series_id: int, submitter_id: int, moderator_id: int
) -> None:
    contribution_id = await _submit_contribution(test_series_id, 4)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(moderator_id))
        approve_response = await client.post(f"/api/v1/contributions/{contribution_id}/approve")
    assert approve_response.status_code == 200

    response = await _vote_as(submitter_id, contribution_id, "endorse")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_single_high_trust_voter_auto_promotes(test_series_id: int, submitter_id: int) -> None:
    voter_id = await _make_user()
    try:
        await _grant_trust(voter_id, test_series_id, approved=80)  # trust_score = 80 >= threshold (75)
        contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 10)

        response = await _vote_as(voter_id, contribution_id, "endorse")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["weight_at_vote"] == 80
        assert body["net_score"] == 80
        assert body["review_status"] == "approved"
        assert body["resolution_method"] == "community_vote"

        async with async_session_factory() as session:
            episode_row = (
                await session.execute(
                    text(
                        "SELECT status, approved_contribution_id FROM episodes "
                        "WHERE series_id = :sid AND episode_number = 10"
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
    finally:
        await _delete_user(voter_id)


@pytest.mark.asyncio
async def test_several_lower_trust_voters_combine_to_cross_threshold(
    test_series_id: int, submitter_id: int
) -> None:
    voter_ids = []
    try:
        for _ in range(3):
            voter_id = await _make_user()
            await _grant_trust(voter_id, test_series_id, approved=30)  # trust_score = 30 each
            voter_ids.append(voter_id)

        contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 11)

        first = await _vote_as(voter_ids[0], contribution_id, "endorse")
        assert first.json()["net_score"] == 30
        assert first.json()["review_status"] == "pending"

        second = await _vote_as(voter_ids[1], contribution_id, "endorse")
        assert second.json()["net_score"] == 60
        assert second.json()["review_status"] == "pending"

        third = await _vote_as(voter_ids[2], contribution_id, "endorse")
        assert third.json()["net_score"] == 90
        assert third.json()["review_status"] == "approved"
        assert third.json()["resolution_method"] == "community_vote"
    finally:
        for voter_id in voter_ids:
            await _delete_user(voter_id)


@pytest.mark.asyncio
async def test_dispute_reduces_net_score_and_blocks_promotion(test_series_id: int, submitter_id: int) -> None:
    endorser_id = await _make_user()
    disputer_id = await _make_user()
    try:
        await _grant_trust(endorser_id, test_series_id, approved=50)
        await _grant_trust(disputer_id, test_series_id, approved=50)

        contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 12)

        endorse_response = await _vote_as(endorser_id, contribution_id, "endorse")
        assert endorse_response.json()["net_score"] == 50

        dispute_response = await _vote_as(disputer_id, contribution_id, "dispute")
        assert dispute_response.json()["net_score"] == 0
        assert dispute_response.json()["review_status"] == "pending"
    finally:
        await _delete_user(endorser_id)
        await _delete_user(disputer_id)


@pytest.mark.asyncio
async def test_negative_trust_score_clamped_to_zero_weight(test_series_id: int, submitter_id: int) -> None:
    voter_id = await _make_user()
    try:
        await _grant_trust(voter_id, test_series_id, rejected=5)  # trust_score = 0 - 5*2 = -10
        contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 13)

        response = await _vote_as(voter_id, contribution_id, "endorse")
        assert response.status_code == 200, response.text
        assert response.json()["weight_at_vote"] == 0
        assert response.json()["net_score"] == 0
    finally:
        await _delete_user(voter_id)


@pytest.mark.asyncio
async def test_my_votes_lists_only_own_votes_with_context(test_series_id: int, submitter_id: int) -> None:
    """#30: GET /contributions/mine/votes — the votes-cast counterpart to
    GET /contributions/mine (own submissions).
    """
    voter_id = await _make_user()
    other_voter_id = await _make_user()
    try:
        contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 20)
        endorse = await _vote_as(voter_id, contribution_id, "endorse")
        assert endorse.status_code == 200

        # A different user's vote on the same contribution must never show
        # up in voter_id's own list.
        other = await _vote_as(other_voter_id, contribution_id, "dispute")
        assert other.status_code == 200

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_session_token(voter_id))
            response = await client.get("/api/v1/contributions/mine/votes")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 1
        entry = body[0]
        assert entry["contribution_id"] == contribution_id
        assert entry["series_id"] == test_series_id
        assert entry["episode_number"] == 20
        assert entry["vote"] == "endorse"
        assert entry["review_status"] == "pending"
    finally:
        await _delete_user(voter_id)
        await _delete_user(other_voter_id)


@pytest.mark.asyncio
async def test_my_votes_requires_authentication() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/contributions/mine/votes")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_weight_at_vote_snapshotted_not_rewritten_by_later_trust_change(
    test_series_id: int, submitter_id: int
) -> None:
    voter_id = await _make_user()
    try:
        await _grant_trust(voter_id, test_series_id, approved=10)  # trust_score = 10 at vote time
        contribution_id = await _submit_contribution_as(submitter_id, test_series_id, 14)

        response = await _vote_as(voter_id, contribution_id, "endorse")
        assert response.json()["weight_at_vote"] == 10

        # Voter's trust rises well past the threshold AFTER voting.
        await _grant_trust(voter_id, test_series_id, approved=100)

        async with async_session_factory() as session:
            snapshotted = (
                await session.execute(
                    text(
                        "SELECT weight_at_vote FROM contribution_votes "
                        "WHERE contribution_id = :cid AND voter_id = :vid"
                    ),
                    {"cid": contribution_id, "vid": voter_id},
                )
            ).scalar_one()
            assert snapshotted == 10  # unchanged despite the voter's trust_score having since risen

            # And the contribution itself must still reflect only the
            # original vote's weight — it must not have been silently
            # re-evaluated/promoted by the later trust change.
            contribution_row = (
                await session.execute(
                    text("SELECT review_status FROM contributions WHERE id = :id"), {"id": contribution_id}
                )
            ).one()
            assert contribution_row.review_status == "pending"
    finally:
        await _delete_user(voter_id)
