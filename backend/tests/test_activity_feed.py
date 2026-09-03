"""Real-Postgres tests for #154's public activity feed —
GET /api/v1/activity and GET /api/v1/activity/rss. Purely a read view over
the existing contributions/series_proposals audit trail (review_status/
reviewed_at) — no new writes. Uses recognizable test-prefixed titles and
cleans up everything it inserts.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from main import app

TEST_PREFIX = "__test_154__"


async def _make_series(title_suffix: str, anilist_id: int) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            return (
                await session.execute(
                    text(
                        "INSERT INTO series (anilist_id, title, provenance) "
                        "VALUES (:aid, :title, 'manami_bootstrap') RETURNING id"
                    ),
                    {"aid": anilist_id, "title": f"{TEST_PREFIX}{title_suffix}"},
                )
            ).scalar_one()


async def _make_citation() -> int:
    async with async_session_factory() as session:
        async with session.begin():
            return (
                await session.execute(
                    text("INSERT INTO citations (url, description) VALUES (NULL, :desc) RETURNING id"),
                    {"desc": f"{TEST_PREFIX}citation"},
                )
            ).scalar_one()


async def _make_contribution(
    series_id: int,
    episode_number: int,
    citation_id: int,
    *,
    review_status: str,
    resolution_method: str | None,
) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            return (
                await session.execute(
                    text(
                        """
                        INSERT INTO contributions
                            (series_id, episode_number, proposed_status, citation_id,
                             review_status, resolution_method, reviewed_at, license_accepted)
                        VALUES (:sid, :epnum, 'canon', :cid, :status, :method,
                                CASE WHEN :status = 'pending' THEN NULL ELSE now() END, true)
                        RETURNING id
                        """
                    ),
                    {
                        "sid": series_id,
                        "epnum": episode_number,
                        "cid": citation_id,
                        "status": review_status,
                        "method": resolution_method,
                    },
                )
            ).scalar_one()


async def _make_series_proposal(title_suffix: str, *, review_status: str) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            return (
                await session.execute(
                    text(
                        """
                        INSERT INTO series_proposals
                            (title, justification, review_status, reviewed_at, license_accepted)
                        VALUES (:title, :just, :status,
                                CASE WHEN :status = 'pending' THEN NULL ELSE now() END, true)
                        RETURNING id
                        """
                    ),
                    {
                        "title": f"{TEST_PREFIX}{title_suffix}",
                        "just": f"{TEST_PREFIX}justification",
                        "status": review_status,
                    },
                )
            ).scalar_one()


async def _cleanup_contribution_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            citation_ids = [
                row.citation_id
                for row in (
                    await session.execute(
                        text("SELECT citation_id FROM contributions WHERE series_id = :sid"), {"sid": series_id}
                    )
                ).fetchall()
            ]
            await session.execute(text("DELETE FROM contributions WHERE series_id = :sid"), {"sid": series_id})
            await session.execute(text("DELETE FROM series WHERE id = :sid"), {"sid": series_id})
            if citation_ids:
                await session.execute(text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids})


async def _cleanup_proposal(proposal_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM series_proposals WHERE id = :id"), {"id": proposal_id})


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_approved_contribution_appears_in_feed(client: AsyncClient) -> None:
    series_id = await _make_series("ApprovedContrib", 991_154_001)
    citation_id = await _make_citation()
    contribution_id = await _make_contribution(
        series_id, 1, citation_id, review_status="approved", resolution_method="moderator"
    )
    try:
        response = await client.get("/api/v1/activity", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["event_type"] == "contribution" and i["id"] == contribution_id)
        assert match["review_status"] == "approved"
        assert match["series_title"] == f"{TEST_PREFIX}ApprovedContrib"
        assert match["episode_number"] == 1
        assert match["proposed_status"] == "canon"
    finally:
        await _cleanup_contribution_series(series_id)


@pytest.mark.asyncio
async def test_withdrawn_contribution_appears_in_feed(client: AsyncClient) -> None:
    series_id = await _make_series("WithdrawnContrib", 991_154_002)
    citation_id = await _make_citation()
    contribution_id = await _make_contribution(
        series_id, 1, citation_id, review_status="withdrawn", resolution_method="withdrawn_by_submitter"
    )
    try:
        response = await client.get("/api/v1/activity", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["event_type"] == "contribution" and i["id"] == contribution_id)
        assert match["review_status"] == "withdrawn"
        assert match["resolution_method"] == "withdrawn_by_submitter"
    finally:
        await _cleanup_contribution_series(series_id)


@pytest.mark.asyncio
async def test_pending_contribution_does_not_appear_in_feed(client: AsyncClient) -> None:
    series_id = await _make_series("PendingContrib", 991_154_003)
    citation_id = await _make_citation()
    contribution_id = await _make_contribution(
        series_id, 1, citation_id, review_status="pending", resolution_method=None
    )
    try:
        response = await client.get("/api/v1/activity", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        assert not any(i["event_type"] == "contribution" and i["id"] == contribution_id for i in items)
    finally:
        await _cleanup_contribution_series(series_id)


@pytest.mark.asyncio
async def test_rejected_series_proposal_appears_in_feed(client: AsyncClient) -> None:
    proposal_id = await _make_series_proposal("RejectedProposal", review_status="rejected")
    try:
        response = await client.get("/api/v1/activity", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["event_type"] == "series_proposal" and i["id"] == proposal_id)
        assert match["review_status"] == "rejected"
        assert match["proposal_title"] == f"{TEST_PREFIX}RejectedProposal"
        assert match["series_id"] is None
    finally:
        await _cleanup_proposal(proposal_id)


@pytest.mark.asyncio
async def test_pending_series_proposal_does_not_appear_in_feed(client: AsyncClient) -> None:
    proposal_id = await _make_series_proposal("PendingProposal", review_status="pending")
    try:
        response = await client.get("/api/v1/activity", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        assert not any(i["event_type"] == "series_proposal" and i["id"] == proposal_id for i in items)
    finally:
        await _cleanup_proposal(proposal_id)


@pytest.mark.asyncio
async def test_feed_ordered_newest_reviewed_first(client: AsyncClient) -> None:
    series_id = await _make_series("Ordering", 991_154_004)
    citation_id = await _make_citation()
    older_id = await _make_contribution(
        series_id, 1, citation_id, review_status="approved", resolution_method="moderator"
    )
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("UPDATE contributions SET reviewed_at = now() - interval '1 hour' WHERE id = :id"),
                {"id": older_id},
            )
    newer_id = await _make_contribution(
        series_id, 2, citation_id, review_status="approved", resolution_method="moderator"
    )
    try:
        response = await client.get("/api/v1/activity", params={"limit": 100})
        assert response.status_code == 200
        items = response.json()["items"]
        ids_in_feed = [i["id"] for i in items if i["event_type"] == "contribution"]
        assert ids_in_feed.index(newer_id) < ids_in_feed.index(older_id)
    finally:
        await _cleanup_contribution_series(series_id)


@pytest.mark.asyncio
async def test_activity_pagination_shape(client: AsyncClient) -> None:
    response = await client.get("/api/v1/activity", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) <= 1
    assert body["total"] >= len(body["items"])


@pytest.mark.asyncio
async def test_rss_feed_returns_xml(client: AsyncClient) -> None:
    series_id = await _make_series("RssItem", 991_154_005)
    citation_id = await _make_citation()
    contribution_id = await _make_contribution(
        series_id, 1, citation_id, review_status="approved", resolution_method="moderator"
    )
    try:
        response = await client.get("/api/v1/activity/rss")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/rss+xml")
        body = response.text
        assert "<rss" in body
        assert f"contribution-{contribution_id}" in body
        assert f"{TEST_PREFIX}RssItem" in body
    finally:
        await _cleanup_contribution_series(series_id)
