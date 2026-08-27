"""Real-Postgres tests for #12 — matches this project's convention
(exercise against a real DB, not mocks). All test data prefixed
__test_12__ / uses a dedicated test series so cleanup is unambiguous and
never touches #4's real bootstrap data or another concurrent test's rows.
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

TEST_SERIES_TITLE = "__test_12__series"


def _unique_id() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


async def _make_authenticated_user() -> int:
    async with async_session_factory() as session:
        async with session.begin():
            user = await login_or_create_user(
                session,
                "github",
                Profile(provider_id=_unique_id(), email=None, display_name="tester", avatar_url=None),
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
                text(
                    "INSERT INTO series (title, provenance) "
                    "VALUES (:title, 'community') RETURNING id"
                ),
                {"title": TEST_SERIES_TITLE},
            )
            return result.scalar_one()


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            # Ordering matters: contributions.citation_id has a plain FK to
            # citations (no ON DELETE CASCADE), so citations can't be
            # deleted while a contribution still references them. Capture
            # the citation AND contribution ids first, delete the series
            # (which CASCADEs to contributions per schema.sql), then clean
            # up the now-unreferenced citations and the outbox_events rows
            # each submission wrote (services/contributions.py always
            # writes one per submission — every one of these tests leaves
            # an unprocessed row behind unless cleaned up here, which was
            # missing on the first pass and broke #9's own worker tests by
            # polluting the batch they poll from — caught by running the
            # FULL suite together, not just this file in isolation).
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
                await session.execute(
                    text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids}
                )
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


@pytest.mark.asyncio
async def test_anonymous_submission_stores_null_submitted_by(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 1,
                "proposed_status": "canon",
                "citation": {"url": "https://example.com", "description": "__test_12__ citation"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["review_status"] == "pending"

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT submitted_by FROM contributions WHERE id = :id"),
                {"id": body["id"]},
            )
        ).one()
        assert row.submitted_by is None


@pytest.mark.asyncio
async def test_submission_methodology_note_is_optional_and_stored(test_series_id: int) -> None:
    """#83: exposed on CitationIn so a public contributor can use the same
    split #77 built for hand-compiled data — description stays short,
    methodology_note carries the fuller research trail. Omitting it must
    still work (it's optional, not a new required field).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with_note = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 8,
                "proposed_status": "canon",
                "citation": {
                    "description": "__test_12__ short claim",
                    "methodology_note": "__test_12__ the fuller research trail",
                },
                "license_accepted": True,
            },
        )
        assert with_note.status_code == 201, with_note.text
        assert with_note.json()["citation"]["methodology_note"] == "__test_12__ the fuller research trail"

        without_note = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 9,
                "proposed_status": "canon",
                "citation": {"description": "__test_12__ no methodology note"},
                "license_accepted": True,
            },
        )
        assert without_note.status_code == 201, without_note.text
        assert without_note.json()["citation"]["methodology_note"] is None


@pytest.mark.asyncio
async def test_submission_missing_license_acceptance_rejected(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 2,
                "proposed_status": "canon",
                "citation": {"description": "__test_12__ citation"},
                "license_accepted": False,
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submission_missing_citation_rejected(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 3,
                "proposed_status": "canon",
                "license_accepted": True,
                # citation omitted entirely
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_pending_rejected_with_existing_id(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 4,
                "proposed_status": "filler",
                "citation": {"description": "__test_12__ first"},
                "license_accepted": True,
            },
        )
        assert first.status_code == 201
        first_id = first.json()["id"]

        second = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 4,
                "proposed_status": "canon",
                "citation": {"description": "__test_12__ second"},
                "license_accepted": True,
            },
        )
    assert second.status_code == 409
    assert second.json()["detail"]["existing_contribution_id"] == first_id


@pytest.mark.asyncio
async def test_contribution_writes_outbox_event(test_series_id: int) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 5,
                "proposed_status": "mixed",
                "citation": {"description": "__test_12__ outbox check"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201
    contribution_id = response.json()["id"]

    # Cleanup of this row happens in the test_series_id fixture's teardown
    # (it now cleans up every outbox_events row for the test series, not
    # just this one) — just assert here.
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT event_type, payload FROM outbox_events "
                    "WHERE event_type = 'contribution.submitted' "
                    "AND payload->>'contribution_id' = :cid"
                ),
                {"cid": str(contribution_id)},
            )
        ).first()
        assert row is not None


@pytest.mark.asyncio
async def test_series_proposal_anonymous_and_mine_scoping() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/series-proposals",
            json={
                "title": "__test_12__ proposed series",
                "justification": "__test_12__ justification",
                "license_accepted": True,
            },
        )
        assert response.status_code == 201, response.text
        proposal_id = response.json()["id"]

        # /mine requires auth — anonymous caller must be rejected
        mine_response = await client.get("/api/v1/series-proposals/mine")
        assert mine_response.status_code == 401

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM series_proposals WHERE id = :id"), {"id": proposal_id}
            )
            # This submission wrote a series_proposal.submitted outbox
            # event too (services/series_proposals.py) — same pollution
            # risk as contributions, cleaned up the same way.
            await session.execute(
                text(
                    "DELETE FROM outbox_events WHERE event_type = 'series_proposal.submitted' "
                    "AND (payload->>'series_proposal_id')::int = :id"
                ),
                {"id": proposal_id},
            )


@pytest.mark.asyncio
async def test_mine_scopes_to_caller_excludes_other_users(test_series_id: int) -> None:
    """The acceptance criterion this issue actually states: /mine excludes
    OTHER users' submissions, not just "requires auth" (already covered
    separately). Two real authenticated users, two real submissions, verify
    each only ever sees their own.
    """
    user_a = await _make_authenticated_user()
    user_b = await _make_authenticated_user()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client_a:
            client_a.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_a))
            resp_a = await client_a.post(
                "/api/v1/contributions",
                json={
                    "series_id": test_series_id,
                    "episode_number": 6,
                    "proposed_status": "canon",
                    "citation": {"description": "__test_12__ user A's citation"},
                    "license_accepted": True,
                },
            )
            assert resp_a.status_code == 201, resp_a.text

        async with AsyncClient(transport=transport, base_url="http://test") as client_b:
            client_b.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_b))
            resp_b = await client_b.post(
                "/api/v1/contributions",
                json={
                    "series_id": test_series_id,
                    "episode_number": 7,
                    "proposed_status": "filler",
                    "citation": {"description": "__test_12__ user B's citation"},
                    "license_accepted": True,
                },
            )
            assert resp_b.status_code == 201, resp_b.text

            mine_b = await client_b.get("/api/v1/contributions/mine")
            assert mine_b.status_code == 200
            mine_b_ids = {c["id"] for c in mine_b.json()}
            assert resp_b.json()["id"] in mine_b_ids
            assert resp_a.json()["id"] not in mine_b_ids  # the actual scoping guarantee
    finally:
        await _delete_user(user_a)
        await _delete_user(user_b)


@pytest.mark.asyncio
async def test_concurrent_submissions_for_same_episode_race_safely(test_series_id: int) -> None:
    """#151: find_pending_for_episode (the #20 pre-check) has a real TOCTOU
    gap — two genuinely concurrent submissions for the same
    (series_id, episode_number) can both pass that check, then race on the
    actual INSERT against contributions_one_pending_per_episode. This must
    exercise the real race, not a sequential duplicate check (already
    covered above by test_duplicate_pending_rejected_with_existing_id,
    which lets the first request fully complete before the second is
    sent) — so two real concurrent requests are fired via asyncio.gather,
    same pattern already proven to genuinely race at the DB level by
    test_moderation.py's test_double_approval_race_is_guarded.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            client.post(
                "/api/v1/contributions",
                json={
                    "series_id": test_series_id,
                    "episode_number": 20,
                    "proposed_status": "canon",
                    "citation": {"description": "__test_151__ racer A"},
                    "license_accepted": True,
                },
            ),
            client.post(
                "/api/v1/contributions",
                json={
                    "series_id": test_series_id,
                    "episode_number": 20,
                    "proposed_status": "filler",
                    "citation": {"description": "__test_151__ racer B"},
                    "license_accepted": True,
                },
            ),
            return_exceptions=True,
        )

    status_codes = sorted(r.status_code if not isinstance(r, BaseException) else -1 for r in responses)
    assert status_codes == [201, 409], [
        r.text if not isinstance(r, BaseException) else repr(r) for r in responses
    ]

    winner = next(r for r in responses if not isinstance(r, BaseException) and r.status_code == 201)
    loser = next(r for r in responses if not isinstance(r, BaseException) and r.status_code == 409)
    # The loser's 409 must point at the winner's real contribution id —
    # not the pre-existing-but-stale sentinel this endpoint would otherwise
    # have no choice but to fall back to if the race left nothing findable.
    assert loser.json()["detail"]["existing_contribution_id"] == winner.json()["id"]

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM contributions WHERE series_id = :sid AND episode_number = 20"),
                {"sid": test_series_id},
            )
        ).scalar_one()
        assert count == 1  # the loser's caught IntegrityError must never leave a duplicate row


@pytest.mark.asyncio
async def test_episode_number_within_known_range_accepted_and_beyond_it_rejected(
    test_series_id: int,
) -> None:
    """#152: a submitted episode number is validated against the series'
    own known real episode count (series.anilist_episode_count, #49's
    AniList sync column) once that count is known. Episode 12 of a
    declared 12-episode show is a normal accepted submission; episode
    9999 of the same show is a clean 422, not a silently-accepted pending
    contribution for an episode that can never really exist.
    """
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("UPDATE series SET anilist_episode_count = 12 WHERE id = :id"),
                {"id": test_series_id},
            )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        in_range = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 12,
                "proposed_status": "canon",
                "citation": {"description": "__test_152__ in-range episode"},
                "license_accepted": True,
            },
        )
        assert in_range.status_code == 201, in_range.text

        out_of_range = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 9999,
                "proposed_status": "canon",
                "citation": {"description": "__test_152__ out-of-range episode"},
                "license_accepted": True,
            },
        )
    assert out_of_range.status_code == 422, out_of_range.text
    assert out_of_range.json()["detail"]["anilist_episode_count"] == 12


@pytest.mark.asyncio
async def test_episode_number_accepted_when_series_count_unknown(test_series_id: int) -> None:
    """A series #49 has never synced (NULL anilist_episode_count — the
    default for every freshly-created test series here, matching a
    brand-new community proposal or a movie/special with no AniList
    entry) must never have submissions blocked just because the real
    count isn't known yet — CLAUDE.md's own guardrail on this exact case.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/contributions",
            json={
                "series_id": test_series_id,
                "episode_number": 5000,
                "proposed_status": "canon",
                "citation": {"description": "__test_152__ unknown-count series"},
                "license_accepted": True,
            },
        )
    assert response.status_code == 201, response.text
