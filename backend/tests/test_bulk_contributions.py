"""Real-Postgres tests for #80 — bulk episode-data submission. Same
conventions as test_contributions.py (#12): dedicated test series, prefixed
test data, full cleanup including the outbox events each submission
writes.
"""

import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from core.security import SESSION_COOKIE_NAME, create_session_token
from main import app
from services.auth import Profile, login_or_create_user

TEST_SERIES_TITLE = "__test_80__series"


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


async def _make_test_series(title_suffix: str = "") -> int:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO series (title, provenance) "
                    "VALUES (:title, 'community') RETURNING id"
                ),
                {"title": f"{TEST_SERIES_TITLE}{title_suffix}"},
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
async def authed_client():
    user_id = await _make_authenticated_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user_id))
        yield client
    await _delete_user(user_id)


@pytest.mark.asyncio
async def test_bulk_submission_creates_one_contribution_per_episode(authed_client: AsyncClient) -> None:
    series_id = await _make_test_series("Basic")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-3",
                "mixed_ranges": "4",
                "filler_ranges": "5-6",
                "citation": {"description": "__test_80__ shared citation"},
                "license_accepted": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["dry_run"] is False
        assert body["declared_count"] == 6
        assert len(body["created"]) == 6
        assert body["skipped_conflicts"] == []
        statuses = {c["episode_number"]: c["proposed_status"] for c in body["created"]}
        assert statuses == {1: "canon", 2: "canon", 3: "canon", 4: "mixed", 5: "filler", 6: "filler"}

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    text("SELECT citation_id FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).all()
            assert len(rows) == 6
            assert len({r.citation_id for r in rows}) == 1  # one shared citation
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_methodology_note_is_optional_and_shared(authed_client: AsyncClient) -> None:
    """#83: the whole batch shares one citation, so its methodology_note
    (like its description) is shared too, not per-episode.
    """
    series_id = await _make_test_series("MethodologyNote")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-2",
                "citation": {
                    "description": "__test_80__ short claim",
                    "methodology_note": "__test_80__ fuller research trail",
                },
                "license_accepted": True,
            },
        )
        assert response.status_code == 200, response.text

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT c.methodology_note FROM contributions co "
                        "JOIN citations c ON c.id = co.citation_id WHERE co.series_id = :sid"
                    ),
                    {"sid": series_id},
                )
            ).all()
            assert len(rows) == 2
            assert all(r.methodology_note == "__test_80__ fuller research trail" for r in rows)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_requires_authentication() -> None:
    series_id = await _make_test_series("Anon")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/series/{series_id}/contributions/bulk",
                json={
                    "canon_ranges": "1",
                    "citation": {"description": "__test_80__ citation"},
                    "license_accepted": True,
                },
            )
        assert response.status_code == 401
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_missing_license_rejected(authed_client: AsyncClient) -> None:
    series_id = await _make_test_series("NoLicense")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1",
                "citation": {"description": "__test_80__ citation"},
                "license_accepted": False,
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_overlapping_categories_rejected_with_no_writes(
    authed_client: AsyncClient,
) -> None:
    series_id = await _make_test_series("Overlap")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-5",
                "filler_ranges": "3-7",
                "citation": {"description": "__test_80__ citation"},
                "license_accepted": True,
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["overlaps"]["canon_filler"] == [3, 4, 5]

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).scalar_one()
            assert count == 0  # rejected before any write
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_malformed_range_rejected(authed_client: AsyncClient) -> None:
    series_id = await _make_test_series("Malformed")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "not-a-number",
                "citation": {"description": "__test_80__ citation"},
                "license_accepted": True,
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_nothing_declared_rejected(authed_client: AsyncClient) -> None:
    series_id = await _make_test_series("Empty")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "citation": {"description": "__test_80__ citation"},
                "license_accepted": True,
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_over_batch_cap_rejected(authed_client: AsyncClient) -> None:
    """Combined-total check: each individual range stays under the
    per-segment bound (#89's DoS fix, tested separately below), but the
    three together exceed MAX_BATCH_SIZE.
    """
    series_id = await _make_test_series("TooBig")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-1000",
                "mixed_ranges": "1001-2000",
                "filler_ranges": "2001-2002",
                "citation": {"description": "__test_80__ citation"},
                "license_accepted": True,
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["max_batch_size"] == 2000
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_oversized_single_range_rejected_cheaply(authed_client: AsyncClient) -> None:
    """Security review (#89): a single range segment far larger than any
    real batch could ever be ("1-999999999999") must be rejected at parse
    time, before ever materializing a huge set in memory — not just
    eventually caught by the combined-total check above.
    """
    series_id = await _make_test_series("HugeSingleRange")
    try:
        started = time.monotonic()
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-999999999999",
                "citation": {"description": "__test_80__ citation"},
                "license_accepted": True,
            },
        )
        elapsed = time.monotonic() - started
        assert response.status_code == 422
        assert "spans" in response.json()["detail"]["message"]
        # The whole point of the fix: rejected without ever materializing
        # a near-trillion-entry set. A generous bound (a real, unbounded
        # attempt would take many seconds and a lot of memory) — this
        # just needs to catch a regression, not be a tight benchmark.
        assert elapsed < 2.0
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_skips_existing_pending_conflict(authed_client: AsyncClient) -> None:
    """#20 applied per-episode within a batch: an episode with someone
    else's pending contribution is skipped, not fatal to the rest.
    """
    series_id = await _make_test_series("Conflict")
    try:
        # A pre-existing pending contribution for episode 5, from a
        # different (anonymous) submission.
        existing = await authed_client.post(
            "/api/v1/contributions",
            json={
                "series_id": series_id,
                "episode_number": 5,
                "proposed_status": "filler",
                "citation": {"description": "__test_80__ pre-existing citation"},
                "license_accepted": True,
            },
        )
        assert existing.status_code == 201, existing.text
        existing_id = existing.json()["id"]

        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-4",
                "filler_ranges": "5",
                "citation": {"description": "__test_80__ bulk citation"},
                "license_accepted": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["declared_count"] == 5
        assert len(body["created"]) == 4  # episodes 1-4 only
        assert body["skipped_conflicts"] == [
            {"episode_number": 5, "existing_contribution_id": existing_id}
        ]
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_dry_run_writes_nothing(authed_client: AsyncClient) -> None:
    series_id = await _make_test_series("DryRun")
    try:
        response = await authed_client.post(
            f"/api/v1/series/{series_id}/contributions/bulk",
            json={
                "canon_ranges": "1-3",
                "citation": {"description": "__test_80__ dry run citation"},
                "license_accepted": True,
                "dry_run": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["dry_run"] is True
        assert len(body["created"]) == 3
        assert all(c["contribution_id"] is None for c in body["created"])

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM contributions WHERE series_id = :sid"),
                    {"sid": series_id},
                )
            ).scalar_one()
            assert count == 0
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_bulk_submission_nonexistent_series_404(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/series/999999999/contributions/bulk",
        json={
            "canon_ranges": "1",
            "citation": {"description": "__test_80__ citation"},
            "license_accepted": True,
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bulk_submission_survives_a_mid_batch_race_on_one_episode(authed_client: AsyncClient) -> None:
    """Security review (#89): the pre-check (find_pending_for_episodes) has
    a real TOCTOU gap — a concurrent submission could create a pending
    contribution for an episode between that check and this batch's own
    insert of it. Simulated deterministically here by mocking the pre-check
    to report "nothing pending" while a real pending contribution already
    exists for episode 3 (inserted directly, bypassing the pre-check
    entirely) — this forces the actual INSERT to hit the real partial
    unique index, exactly like a genuine race would. Without the
    savepoint fix, this would abort the whole transaction and silently
    discard episodes 1, 2, and 4 too.
    """
    series_id = await _make_test_series("RaceCondition")
    try:
        existing = await authed_client.post(
            "/api/v1/contributions",
            json={
                "series_id": series_id,
                "episode_number": 3,
                "proposed_status": "filler",
                "citation": {"description": "__test_80__ pre-existing citation"},
                "license_accepted": True,
            },
        )
        assert existing.status_code == 201, existing.text
        existing_id = existing.json()["id"]

        with patch(
            "services.contributions.contributions_repo.find_pending_for_episodes",
            new=AsyncMock(return_value={}),  # simulates the pre-check seeing nothing
        ):
            response = await authed_client.post(
                f"/api/v1/series/{series_id}/contributions/bulk",
                json={
                    "canon_ranges": "1-4",
                    "citation": {"description": "__test_80__ bulk citation"},
                    "license_accepted": True,
                },
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["declared_count"] == 4
        created_episodes = {c["episode_number"] for c in body["created"]}
        assert created_episodes == {1, 2, 4}  # episode 3 didn't poison the rest
        assert body["skipped_conflicts"] == [
            {"episode_number": 3, "existing_contribution_id": existing_id}
        ]

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM contributions WHERE series_id = :sid AND episode_number != 3"),
                    {"sid": series_id},
                )
            ).scalar_one()
            assert count == 3  # 1, 2, 4 really committed, not rolled back
    finally:
        await _cleanup_series(series_id)
