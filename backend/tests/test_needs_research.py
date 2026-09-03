"""Real-Postgres tests for #153's public "needs research" queue —
GET /api/v1/series/needs-research. Combines two cases into one unified
query (see repositories/series.py's list_needs_research): a series with
zero `episodes` rows (`never_researched`), and a series #175's drift
worker has flagged (`status_drift` / `episode_count_drift`, read straight
from `series.anilist_drift_reason`). Uses recognizable test-prefixed
titles and cleans up everything it inserts, safe to run against a
database that already has real bootstrap data loaded.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from main import app

TEST_PREFIX = "__test_153__"


async def _make_series(
    title_suffix: str,
    anilist_id: int,
    *,
    drift_reason: str | None = None,
    drift_flagged: bool = False,
) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            series_id = (
                await session.execute(
                    text(
                        """
                        INSERT INTO series
                            (anilist_id, title, provenance, anilist_drift_reason, anilist_drift_flagged_at)
                        VALUES
                            (:aid, :title, 'manami_bootstrap', :reason,
                             CASE WHEN :flagged THEN now() ELSE NULL END)
                        RETURNING id
                        """
                    ),
                    {
                        "aid": anilist_id,
                        "title": f"{TEST_PREFIX}{title_suffix}",
                        "reason": drift_reason,
                        "flagged": drift_flagged,
                    },
                )
            ).scalar_one()
    return series_id


async def _make_citation() -> int:
    async with async_session_factory() as session:
        async with session.begin():
            return (
                await session.execute(
                    text("INSERT INTO citations (url, description) VALUES (NULL, :desc) RETURNING id"),
                    {"desc": f"{TEST_PREFIX}citation"},
                )
            ).scalar_one()


async def _add_approved_episode(series_id: int, episode_number: int, citation_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            contribution_id = (
                await session.execute(
                    text(
                        """
                        INSERT INTO contributions
                            (series_id, episode_number, proposed_status, citation_id,
                             review_status, resolution_method, license_accepted)
                        VALUES (:sid, :epnum, 'canon', :cid, 'approved', 'moderator', true)
                        RETURNING id
                        """
                    ),
                    {"sid": series_id, "epnum": episode_number, "cid": citation_id},
                )
            ).scalar_one()
            await session.execute(
                text(
                    """
                    INSERT INTO episodes (series_id, episode_number, status, citation_id, approved_contribution_id)
                    VALUES (:sid, :epnum, 'canon', :cid, :contrib_id)
                    """
                ),
                {"sid": series_id, "epnum": episode_number, "cid": citation_id, "contrib_id": contribution_id},
            )


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM episodes WHERE series_id = :sid"), {"sid": series_id})
            await session.execute(text("DELETE FROM contributions WHERE series_id = :sid"), {"sid": series_id})
            await session.execute(text("DELETE FROM series WHERE id = :sid"), {"sid": series_id})


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_zero_episode_series_appears_as_never_researched(client: AsyncClient) -> None:
    series_id = await _make_series("NeverResearched", 991_153_001)
    try:
        response = await client.get("/api/v1/series/needs-research", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["id"] == series_id)
        assert match["reason"] == "never_researched"
        assert match["researched_episode_count"] == 0
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_status_drift_series_appears_with_correct_reason(client: AsyncClient) -> None:
    series_id = await _make_series(
        "StatusDrift", 991_153_002, drift_reason="status_drift", drift_flagged=True
    )
    citation_id = await _make_citation()
    try:
        # Carries episodes already (a drift-flagged series always has been
        # researched before — never_researched and drift are mutually
        # exclusive per #153's own scope note).
        await _add_approved_episode(series_id, 1, citation_id)
        response = await client.get("/api/v1/series/needs-research", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["id"] == series_id)
        assert match["reason"] == "status_drift"
        assert match["researched_episode_count"] == 1
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episode_count_drift_series_appears_with_correct_reason(client: AsyncClient) -> None:
    series_id = await _make_series(
        "EpisodeCountDrift", 991_153_003, drift_reason="episode_count_drift", drift_flagged=True
    )
    citation_id = await _make_citation()
    try:
        await _add_approved_episode(series_id, 1, citation_id)
        response = await client.get("/api/v1/series/needs-research", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["id"] == series_id)
        assert match["reason"] == "episode_count_drift"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_fully_researched_non_drifted_series_does_not_appear(client: AsyncClient) -> None:
    series_id = await _make_series("FullyResearched", 991_153_004)
    citation_id = await _make_citation()
    try:
        await _add_approved_episode(series_id, 1, citation_id)
        response = await client.get("/api/v1/series/needs-research", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        assert not any(i["id"] == series_id for i in items)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_needs_research_pagination_shape(client: AsyncClient) -> None:
    response = await client.get("/api/v1/series/needs-research", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) <= 1
    assert body["total"] >= len(body["items"])
