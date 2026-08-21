"""Real-Postgres tests for #7's read endpoints. Uses recognizable
test-prefixed titles and cleans up everything it inserts, in dependency
order — safe to run against a database that already has real data loaded
by another process (e.g. #4's bootstrap import), since nothing here
touches a row it didn't create itself.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from core.db import async_session_factory
from main import app

TEST_PREFIX = "__test_7__"


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            # contributions/episodes/citations/votes cascade or are cleaned
            # explicitly since citations has no FK back to series.
            await session.execute(
                text(
                    "DELETE FROM contribution_votes WHERE contribution_id IN "
                    "(SELECT id FROM contributions WHERE series_id = :sid)"
                ),
                {"sid": series_id},
            )
            await session.execute(
                text("DELETE FROM episodes WHERE series_id = :sid"), {"sid": series_id}
            )
            await session.execute(
                text("DELETE FROM contributions WHERE series_id = :sid"), {"sid": series_id}
            )
            await session.execute(
                text("DELETE FROM series_synonyms WHERE series_id = :sid"), {"sid": series_id}
            )
            await session.execute(text("DELETE FROM series WHERE id = :sid"), {"sid": series_id})


async def _make_series(title_suffix: str, anilist_id: int) -> int:
    async with async_session_factory() as session:
        async with session.begin():
            series_id = (
                await session.execute(
                    text(
                        "INSERT INTO series (anilist_id, title, provenance) "
                        "VALUES (:anilist_id, :title, 'manami_bootstrap') RETURNING id"
                    ),
                    {"anilist_id": anilist_id, "title": f"{TEST_PREFIX}{title_suffix}"},
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO series_synonyms (series_id, synonym) VALUES (:sid, :syn)"
                ),
                {"sid": series_id, "syn": f"{TEST_PREFIX}synonym-{title_suffix}"},
            )
    return series_id


async def _make_citation() -> int:
    async with async_session_factory() as session:
        async with session.begin():
            return (
                await session.execute(
                    text(
                        "INSERT INTO citations (url, description) "
                        "VALUES (NULL, :desc) RETURNING id"
                    ),
                    {"desc": f"{TEST_PREFIX}citation"},
                )
            ).scalar_one()


async def _make_approved_episode(series_id: int, episode_number: int, citation_id: int) -> int:
    """Mimics what #12/#13 will eventually do: a contribution promoted to
    an episodes row. Built directly here since those issues aren't built
    yet."""
    async with async_session_factory() as session:
        async with session.begin():
            contribution_id = (
                await session.execute(
                    text(
                        "INSERT INTO contributions "
                        "(series_id, episode_number, proposed_status, citation_id, "
                        " review_status, resolution_method, license_accepted) "
                        "VALUES (:sid, :epnum, 'canon', :cid, 'approved', 'moderator', true) "
                        "RETURNING id"
                    ),
                    {"sid": series_id, "epnum": episode_number, "cid": citation_id},
                )
            ).scalar_one()
            episode_id = (
                await session.execute(
                    text(
                        "INSERT INTO episodes "
                        "(series_id, episode_number, status, citation_id, approved_contribution_id) "
                        "VALUES (:sid, :epnum, 'canon', :cid, :contrib_id) RETURNING id"
                    ),
                    {
                        "sid": series_id,
                        "epnum": episode_number,
                        "cid": citation_id,
                        "contrib_id": contribution_id,
                    },
                )
            ).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO contribution_votes (contribution_id, vote, weight_at_vote) "
                    "VALUES (:cid, 'endorse', 5)"
                ),
                {"cid": contribution_id},
            )
    return episode_id


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_series_sort_recently_updated_orders_by_latest_episode(client: AsyncClient) -> None:
    """#42: a series with a more recently-approved episode sorts first; a
    series with no episodes at all sorts last (NULLS LAST), not dropped.
    """
    older_series_id = await _make_series("Older", anilist_id=900101)
    newer_series_id = await _make_series("Newer", anilist_id=900102)
    empty_series_id = await _make_series("Empty", anilist_id=900103)
    try:
        citation_id = await _make_citation()
        await _make_approved_episode(older_series_id, 1, citation_id)
        async with async_session_factory() as session:
            async with session.begin():
                # Force a real, distinguishable ordering rather than relying
                # on two now()-default inserts landing in the right order.
                await session.execute(
                    text("UPDATE episodes SET updated_at = now() - interval '1 day' WHERE series_id = :sid"),
                    {"sid": older_series_id},
                )
        await _make_approved_episode(newer_series_id, 1, citation_id)

        response = await client.get(
            "/api/v1/series", params={"sort": "recently_updated", "limit": 100}
        )
        assert response.status_code == 200
        ids_in_order = [item["id"] for item in response.json()["items"]]

        test_ids = {older_series_id, newer_series_id, empty_series_id}
        ordered_test_ids = [i for i in ids_in_order if i in test_ids]
        assert ordered_test_ids == [newer_series_id, older_series_id, empty_series_id]
    finally:
        await _cleanup_series(older_series_id)
        await _cleanup_series(newer_series_id)
        await _cleanup_series(empty_series_id)


@pytest.mark.asyncio
async def test_series_invalid_sort_value_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/series", params={"sort": "not_a_real_sort"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_series_search_by_title_and_synonym(client: AsyncClient) -> None:
    series_id = await _make_series("Alpha", anilist_id=900001)
    try:
        by_title = await client.get("/api/v1/series", params={"q": f"{TEST_PREFIX}Alpha"})
        assert by_title.status_code == 200
        assert any(item["id"] == series_id for item in by_title.json()["items"])

        by_synonym = await client.get(
            "/api/v1/series", params={"q": f"{TEST_PREFIX}synonym-Alpha"}
        )
        assert any(item["id"] == series_id for item in by_synonym.json()["items"])

        by_anilist = await client.get("/api/v1/series", params={"anilist_id": 900001})
        body = by_anilist.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == series_id
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_pagination_shape(client: AsyncClient) -> None:
    response = await client.get("/api/v1/series", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert len(body["items"]) <= 1


@pytest.mark.asyncio
async def test_series_detail_includes_synonyms(client: AsyncClient) -> None:
    series_id = await _make_series("Beta", anilist_id=900002)
    try:
        response = await client.get(f"/api/v1/series/{series_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == series_id
        assert f"{TEST_PREFIX}synonym-Beta" in body["synonyms"]
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_detail_404() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/series/999999999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_episodes_list_includes_citation(client: AsyncClient) -> None:
    series_id = await _make_series("Gamma", anilist_id=900003)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["episode_number"] == 1
        assert body[0]["citation"]["id"] == citation_id
        assert body[0]["citation"]["description"] == f"{TEST_PREFIX}citation"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episode_history_reflects_resolution_and_votes(client: AsyncClient) -> None:
    series_id = await _make_series("Delta", anilist_id=900004)
    citation_id = await _make_citation()
    episode_id = await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/episodes/{episode_id}/history")
        assert response.status_code == 200
        history = response.json()
        assert len(history) == 1
        entry = history[0]
        assert entry["review_status"] == "approved"
        assert entry["resolution_method"] == "moderator"
        assert entry["submitted_by"] is None  # anonymous, per the fixture
        assert len(entry["votes"]) == 1
        assert entry["votes"][0]["vote"] == "endorse"
        assert entry["votes"][0]["weight_at_vote"] == 5
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episode_history_empty_for_episode_with_no_contributions(
    client: AsyncClient,
) -> None:
    series_id = await _make_series("Epsilon", anilist_id=900005)
    citation_id = await _make_citation()
    episode_id = await _make_approved_episode(series_id, 1, citation_id)
    try:
        # A second episode, same series, with its OWN contribution — proves
        # history is scoped correctly and doesn't leak across episodes.
        response = await client.get(f"/api/v1/episodes/{episode_id}/history")
        assert len(response.json()) == 1
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episode_404() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/episodes/999999999")
        assert response.status_code == 404
        history_response = await client.get("/api/v1/episodes/999999999/history")
        assert history_response.status_code == 404
