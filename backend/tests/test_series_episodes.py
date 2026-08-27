"""Real-Postgres tests for #7's read endpoints. Uses recognizable
test-prefixed titles and cleans up everything it inserts, in dependency
order — safe to run against a database that already has real data loaded
by another process (e.g. #4's bootstrap import), since nothing here
touches a row it didn't create itself.
"""

from datetime import date

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
    """#42: a series with a more recently-approved episode sorts first.
    #47 changed the second half of this test's own original claim: a
    zero-episode series used to sort last (NULLS LAST) rather than being
    dropped — now a plain browse (no q/id) excludes it entirely, so it
    must not appear in the results at all, not just sort after everything
    else.
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
        assert ordered_test_ids == [newer_series_id, older_series_id]
    finally:
        await _cleanup_series(older_series_id)
        await _cleanup_series(newer_series_id)
        await _cleanup_series(empty_series_id)


@pytest.mark.asyncio
async def test_series_default_browse_excludes_zero_episode_series(client: AsyncClient) -> None:
    """#47: a plain browse (no q, no external id) excludes series with no
    episode data at all — most of the bootstrap-imported catalog, which
    made the default grid mostly empty "no episodes yet" pages.
    """
    empty_series_id = await _make_series("NoEpisodesAtAll", anilist_id=900201)
    researched_series_id = await _make_series("HasEpisodes", anilist_id=900202)
    try:
        citation_id = await _make_citation()
        await _make_approved_episode(researched_series_id, 1, citation_id)

        response = await client.get("/api/v1/series", params={"limit": 100})
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["items"]}
        assert empty_series_id not in ids
        assert researched_series_id in ids
    finally:
        await _cleanup_series(empty_series_id)
        await _cleanup_series(researched_series_id)


@pytest.mark.asyncio
async def test_series_targeted_lookup_still_returns_zero_episode_series(
    client: AsyncClient,
) -> None:
    """#47: the exclusion above is for the default browse grid only — a
    contributor specifically searching for a show (by title or by external
    id) must still find an unresearched catalog entry, or they'd have no
    way to tell it apart from "doesn't exist yet" and would file a
    duplicate series proposal.
    """
    empty_series_id = await _make_series("FindableStub", anilist_id=900203)
    try:
        by_title = await client.get(
            "/api/v1/series", params={"q": f"{TEST_PREFIX}FindableStub"}
        )
        assert any(item["id"] == empty_series_id for item in by_title.json()["items"])

        by_anilist = await client.get("/api/v1/series", params={"anilist_id": 900203})
        assert any(item["id"] == empty_series_id for item in by_anilist.json()["items"])
    finally:
        await _cleanup_series(empty_series_id)


@pytest.mark.asyncio
async def test_series_detail_and_episodes_unaffected_by_zero_episode_hiding(
    client: AsyncClient,
) -> None:
    """#47 explicitly does NOT change GET /series/{id} or its /episodes —
    only the browse/search list hides zero-episode series. Direct access
    (e.g. from a search result, or a moderator's own record) must keep
    working exactly as before: 200, empty episode list.
    """
    empty_series_id = await _make_series("DirectAccessStillWorks", anilist_id=900204)
    try:
        detail = await client.get(f"/api/v1/series/{empty_series_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == empty_series_id

        episodes = await client.get(f"/api/v1/series/{empty_series_id}/episodes")
        assert episodes.status_code == 200
        assert episodes.json() == []
    finally:
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
async def test_series_detail_includes_anilist_episode_count(client: AsyncClient) -> None:
    """#49's real episode total, independent of how many episodes have
    actually been hand-researched — null until the sync worker has
    reached this series at least once.
    """
    series_id = await _make_series("Zeta", anilist_id=900008)
    try:
        response = await client.get(f"/api/v1/series/{series_id}")
        assert response.status_code == 200
        assert response.json()["anilist_episode_count"] is None

        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE series SET anilist_episode_count = 500 WHERE id = :sid"),
                    {"sid": series_id},
                )
        response = await client.get(f"/api/v1/series/{series_id}")
        assert response.json()["anilist_episode_count"] == 500
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_airing_status_surfaced_on_list_and_detail(client: AsyncClient) -> None:
    """#111: AniList's own MediaStatus (FINISHED/RELEASING/...), synced by
    #49's worker — null until the sync worker has reached this series at
    least once, same convention as anilist_episode_count above.
    """
    series_id = await _make_series("Eta", anilist_id=900009)
    try:
        response = await client.get(f"/api/v1/series/{series_id}")
        assert response.status_code == 200
        assert response.json()["airing_status"] is None

        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE series SET anilist_status = 'RELEASING' WHERE id = :sid"),
                    {"sid": series_id},
                )
        response = await client.get(f"/api/v1/series/{series_id}")
        assert response.json()["airing_status"] == "RELEASING"

        list_response = await client.get("/api/v1/series", params={"anilist_id": 900009})
        item = list_response.json()["items"][0]
        assert item["airing_status"] == "RELEASING"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_detail_includes_description_and_dates(client: AsyncClient) -> None:
    """#126: AniList's synced synopsis + air-date range — null until the
    sync worker has reached this series at least once, same convention as
    anilist_episode_count/airing_status above. Only exposed on the detail
    response, never the browse/search list (the about-card/era-tile only
    render on the series detail page — see CLAUDE.md scope note for #126).
    """
    series_id = await _make_series("Theta", anilist_id=900010)
    try:
        response = await client.get(f"/api/v1/series/{series_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["description"] is None
        assert body["start_date"] is None
        assert body["end_date"] is None

        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE series SET anilist_description = :desc, "
                        "anilist_start_date = :start, anilist_end_date = :end "
                        "WHERE id = :sid"
                    ),
                    {
                        "desc": "A cleaned synopsis.",
                        # asyncpg requires a real date object for a DATE
                        # column parameter, not an ISO string.
                        "start": date(1999, 10, 3),
                        "end": date(2007, 2, 8),
                        "sid": series_id,
                    },
                )
        response = await client.get(f"/api/v1/series/{series_id}")
        body = response.json()
        assert body["description"] == "A cleaned synopsis."
        assert body["start_date"] == "1999-10-03"
        assert body["end_date"] == "2007-02-08"

        # Not on the list/browse response — deliberately not bloating it.
        list_response = await client.get("/api/v1/series", params={"anilist_id": 900010})
        item = list_response.json()["items"][0]
        assert "description" not in item
        assert "start_date" not in item
        assert "end_date" not in item
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_detail_includes_related_series(client: AsyncClient) -> None:
    """Lightweight cross-links for shows split across multiple AniList
    entries (e.g. Fairy Tail / Fairy Tail (2014) / Fairy Tail (2018)) —
    empty for the vast majority of series, populated only when
    series_relations rows exist.
    """
    a_id = await _make_series("RelatedA", anilist_id=900009)
    b_id = await _make_series("RelatedB", anilist_id=900010)
    try:
        response = await client.get(f"/api/v1/series/{a_id}")
        assert response.json()["related_series"] == []

        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO series_relations (series_id, related_series_id) "
                        "VALUES (:a, :b), (:b, :a)"
                    ),
                    {"a": a_id, "b": b_id},
                )

        response = await client.get(f"/api/v1/series/{a_id}")
        related = response.json()["related_series"]
        assert len(related) == 1
        assert related[0]["id"] == b_id
        assert related[0]["title"] == f"{TEST_PREFIX}RelatedB"
    finally:
        await _cleanup_series(a_id)
        await _cleanup_series(b_id)


@pytest.mark.asyncio
async def test_series_lookup_by_slug_and_id_resolve_the_same_series(client: AsyncClient) -> None:
    """#116: slug-based series URLs. Both the numeric id and the slug
    generated from its title must resolve to the identical series.
    """
    series_id = await _make_series("SlugLookup", anilist_id=900401)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE series SET slug = :slug WHERE id = :id"),
                    {"slug": f"__test-7__sluglookup-{series_id}", "id": series_id},
                )

        by_id = await client.get(f"/api/v1/series/{series_id}")
        assert by_id.status_code == 200
        assert by_id.json()["id"] == series_id

        by_slug = await client.get(f"/api/v1/series/__test-7__sluglookup-{series_id}")
        assert by_slug.status_code == 200
        assert by_slug.json()["id"] == series_id
        assert by_slug.json()["slug"] == f"__test-7__sluglookup-{series_id}"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_series_lookup_by_unknown_slug_404s(client: AsyncClient) -> None:
    """#116: an identifier that isn't purely numeric is always treated as
    a slug lookup, never coerced to an id — an unknown slug 404s cleanly
    rather than erroring.
    """
    response = await client.get("/api/v1/series/this-slug-does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_series_create_generates_slug_with_collision_disambiguation(
    client: AsyncClient,
) -> None:
    """#116: repositories.series.create() (used when a series_proposal is
    approved) generates a slug the same way the one-time backfill does,
    including disambiguating a base-slug collision by appending the new
    row's own id.
    """
    import repositories.series as series_repo

    async with async_session_factory() as session:
        async with session.begin():
            first = await series_repo.create(
                session,
                title=f"{TEST_PREFIX}Collision Show",
                anilist_id=900402,
                mal_id=None,
                anidb_id=None,
                provenance="community",
                added_by=None,
            )
    try:
        assert first.slug == "test-7-collision-show"

        async with async_session_factory() as session:
            async with session.begin():
                second = await series_repo.create(
                    session,
                    # Different title, same slugified form once punctuation
                    # is stripped — the exact collision scenario #116 calls
                    # out (e.g. "Fairy Tail" vs "Fairy Tail!" both slugify
                    # to "fairy-tail").
                    title=f"{TEST_PREFIX}Collision, Show!!",
                    anilist_id=900403,
                    mal_id=None,
                    anidb_id=None,
                    provenance="community",
                    added_by=None,
                )
        try:
            assert second.slug == f"test-7-collision-show-{second.id}"
        finally:
            await _cleanup_series(second.id)
    finally:
        await _cleanup_series(first.id)


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
async def test_episodes_list_aired_at_null_when_not_scheduled(client: AsyncClient) -> None:
    """#49's series_episode_schedule sync is independent of episode research
    — most researched episodes won't have a matching schedule row yet
    (either never synced, or AniList's own schedule data doesn't reach back
    that far for an old finished show). aired_at must come back null, not
    error or a missing key.
    """
    series_id = await _make_series("NoSchedule", anilist_id=900006)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["aired_at"] is None
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_includes_aired_at_when_scheduled(client: AsyncClient) -> None:
    series_id = await _make_series("HasSchedule", anilist_id=900007)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO series_episode_schedule (series_id, episode_number, aired_at) "
                        "VALUES (:sid, 1, '2007-02-15T12:00:00Z')"
                    ),
                    {"sid": series_id},
                )
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["aired_at"] == "2007-02-15T12:00:00Z"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_title_null_by_default(client: AsyncClient) -> None:
    """#73: most episodes, including researched ones, won't have a title
    for a long time — must come back null, not error or a missing key.
    """
    series_id = await _make_series("NoTitle", anilist_id=900301)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["title"] is None
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_includes_title_when_set(client: AsyncClient) -> None:
    series_id = await _make_series("HasTitle", anilist_id=900302)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE episodes SET title = :t WHERE series_id = :sid AND episode_number = 1"),
                    {"sid": series_id, "t": f"{TEST_PREFIX}Enter: Naruto Uzumaki!"},
                )
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["title"] == f"{TEST_PREFIX}Enter: Naruto Uzumaki!"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_citation_source_count_defaults_to_one(client: AsyncClient) -> None:
    """#74: a plain single-source citation (the common case, and what
    every existing pre-#74 citation row implicitly is) must not imply a
    corroboration claim that was never made.
    """
    series_id = await _make_series("SingleSource", anilist_id=900303)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["citation"]["source_count"] == 1
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_citation_source_count_reflects_corroboration(
    client: AsyncClient,
) -> None:
    series_id = await _make_series("Corroborated", anilist_id=900304)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE citations SET source_count = 2 WHERE id = :cid"),
                    {"cid": citation_id},
                )
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["citation"]["source_count"] == 2
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_methodology_note_null_by_default(client: AsyncClient) -> None:
    """#77: a citation with nothing more to say than its short description
    must come back null, not error or a missing key — the frontend renders
    no disclosure at all in that case.
    """
    series_id = await _make_series("NoMethodologyNote", anilist_id=900305)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["citation"]["methodology_note"] is None
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_includes_methodology_note_when_set(client: AsyncClient) -> None:
    series_id = await _make_series("HasMethodologyNote", anilist_id=900306)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE citations SET methodology_note = :m WHERE id = :cid"),
                    {"cid": citation_id, "m": f"{TEST_PREFIX}full research trail"},
                )
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["citation"]["methodology_note"] == f"{TEST_PREFIX}full research trail"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_has_pending_contribution_false_by_default(client: AsyncClient) -> None:
    """#87: an episode with no pending contribution at all — the common
    case — must come back false, not null or a missing key.
    """
    series_id = await _make_series("NoPending", anilist_id=900307)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    try:
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        assert response.json()[0]["has_pending_contribution"] is False
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_episodes_list_has_pending_contribution_true_when_pending_exists(
    client: AsyncClient,
) -> None:
    """#87: a second, unrelated episode in the same series stays false —
    proves the LEFT JOIN is scoped per (series_id, episode_number), not
    leaking a pending flag across every episode in the series.
    """
    series_id = await _make_series("HasPending", anilist_id=900308)
    citation_id = await _make_citation()
    await _make_approved_episode(series_id, 1, citation_id)
    await _make_approved_episode(series_id, 2, citation_id)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO contributions "
                        "(series_id, episode_number, proposed_status, citation_id, license_accepted) "
                        "VALUES (:sid, 1, 'filler', :cid, true)"
                    ),
                    {"sid": series_id, "cid": citation_id},
                )
        response = await client.get(f"/api/v1/series/{series_id}/episodes")
        assert response.status_code == 200
        by_episode = {row["episode_number"]: row["has_pending_contribution"] for row in response.json()}
        assert by_episode == {1: True, 2: False}
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
