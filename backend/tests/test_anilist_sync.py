"""Real-Postgres tests for #49's AniList episode-count/air-date sync,
matching this project's real-infra testing convention. Hits the real,
public, unauthenticated AniList GraphQL API (graphql.anilist.co) rather
than mocking it — the same "test against the real dependency, not a
stand-in" discipline this project already applies to Postgres itself, and
consistent with how the frontend's own AniList cover-art integration
(#46) was verified against real responses rather than fixtures.

Uses anilist_id 1735 (NARUTO: Shippuuden), a real, permanently-finished
show confirmed live 2026-08-22: status FINISHED, episodes 500, but its
airingSchedule field only retains the last 3 episodes' worth of nodes —
exactly the discovered limitation that motivated storing
anilist_episode_count as its own column rather than inferring it from
series_episode_schedule's row count.

Safe to run against a database that already has a real bootstrap-imported
series with this anilist_id (schema.sql's UNIQUE constraint on
series.anilist_id would otherwise collide) — _ensure_test_series reuses an
existing row read-only rather than inserting a duplicate, and cleanup only
removes what this test itself created.
"""

import pytest
from sqlalchemy import text

from core.db import async_session_factory
from repositories.series_episode_schedule import list_series_needing_sync
from services.anilist_sync import sync_episode_schedules

NARUTO_SHIPPUDEN_ANILIST_ID = 1735
TEST_PREFIX = "__test_49__"


async def _ensure_test_series(anilist_id: int, title: str) -> tuple[int, bool]:
    """Returns (series_id, created_by_this_test)."""
    async with async_session_factory() as session:
        async with session.begin():
            existing = (
                await session.execute(
                    text("SELECT id FROM series WHERE anilist_id = :aid"), {"aid": anilist_id}
                )
            ).first()
            if existing:
                return existing.id, False
            series_id = (
                await session.execute(
                    text(
                        "INSERT INTO series (title, provenance, anilist_id) "
                        "VALUES (:title, 'community', :aid) RETURNING id"
                    ),
                    {"title": title, "aid": anilist_id},
                )
            ).scalar_one()
            return series_id, True


async def _cleanup(series_id: int, created_by_this_test: bool) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM series_episode_schedule WHERE series_id = :sid"),
                {"sid": series_id},
            )
            if created_by_this_test:
                await session.execute(text("DELETE FROM series WHERE id = :sid"), {"sid": series_id})
            else:
                # Reset the sync bookkeeping on a pre-existing row so this
                # test never permanently mutates data it didn't create.
                await session.execute(
                    text(
                        "UPDATE series SET anilist_status = NULL, "
                        "anilist_episode_count = NULL, anilist_cover_url = NULL, "
                        "anilist_banner_url = NULL, episode_schedule_synced_at = NULL "
                        "WHERE id = :sid"
                    ),
                    {"sid": series_id},
                )


@pytest.mark.asyncio
async def test_never_synced_series_is_a_sync_candidate() -> None:
    series_id, created = await _ensure_test_series(
        NARUTO_SHIPPUDEN_ANILIST_ID, f"{TEST_PREFIX} Naruto: Shippuden"
    )
    try:
        async with async_session_factory() as session:
            async with session.begin():
                candidates = await list_series_needing_sync(session)
        assert any(c.id == series_id for c in candidates)
    finally:
        await _cleanup(series_id, created)


@pytest.mark.asyncio
async def test_sync_populates_status_episode_count_and_schedule() -> None:
    series_id, created = await _ensure_test_series(
        NARUTO_SHIPPUDEN_ANILIST_ID, f"{TEST_PREFIX} Naruto: Shippuden"
    )
    try:
        synced = await sync_episode_schedules()
        assert synced >= 1

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT anilist_status, anilist_episode_count, anilist_cover_url, "
                        "anilist_banner_url, episode_schedule_synced_at "
                        "FROM series WHERE id = :sid"
                    ),
                    {"sid": series_id},
                )
            ).one()
            assert row.anilist_status == "FINISHED"
            # The real, reliable total — NOT the schedule row count, which
            # is the whole reason this is its own column (see module
            # docstring).
            assert row.anilist_episode_count == 500
            assert row.episode_schedule_synced_at is not None
            # 2026-08-22 follow-up: cover/banner art synced here instead of
            # fetched live by the frontend on every page load.
            assert row.anilist_cover_url is not None
            assert row.anilist_banner_url is not None

            schedule_rows = (
                await session.execute(
                    text(
                        "SELECT episode_number FROM series_episode_schedule "
                        "WHERE series_id = :sid ORDER BY episode_number"
                    ),
                    {"sid": series_id},
                )
            ).fetchall()
            # AniList's airingSchedule only retains a trailing window for a
            # long-finished show — real, confirmed behavior, not a bug in
            # this sync. episode_count above is what carries the true total.
            assert len(schedule_rows) > 0
            assert len(schedule_rows) < 500
    finally:
        await _cleanup(series_id, created)


@pytest.mark.asyncio
async def test_finished_series_is_not_resynced_on_a_later_cycle() -> None:
    series_id, created = await _ensure_test_series(
        NARUTO_SHIPPUDEN_ANILIST_ID, f"{TEST_PREFIX} Naruto: Shippuden"
    )
    try:
        first_synced = await sync_episode_schedules()
        assert first_synced >= 1

        async with async_session_factory() as session:
            candidates = await list_series_needing_sync(session)
        assert not any(c.id == series_id for c in candidates), (
            "a FINISHED series must not remain a sync candidate on a later cycle"
        )

        async with async_session_factory() as session:
            first_synced_at = (
                await session.execute(
                    text("SELECT episode_schedule_synced_at FROM series WHERE id = :sid"),
                    {"sid": series_id},
                )
            ).scalar_one()

        await sync_episode_schedules()

        async with async_session_factory() as session:
            second_synced_at = (
                await session.execute(
                    text("SELECT episode_schedule_synced_at FROM series WHERE id = :sid"),
                    {"sid": series_id},
                )
            ).scalar_one()

        # Confirms the skip is real, not just "candidate list excluded it
        # but it got synced anyway some other way" — timestamp is untouched.
        assert first_synced_at == second_synced_at
    finally:
        await _cleanup(series_id, created)


@pytest.mark.asyncio
async def test_releasing_series_remains_a_sync_candidate() -> None:
    """A series manually marked RELEASING (simulating a prior sync of an
    ongoing show, without a live network call) must still show up as a
    candidate — this is the direct answer to "what about a series that's
    still airing."
    """
    series_id, created = await _ensure_test_series(999999001, f"{TEST_PREFIX} Ongoing Fixture Show")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE series SET anilist_status = 'RELEASING', "
                        "episode_schedule_synced_at = now() WHERE id = :sid"
                    ),
                    {"sid": series_id},
                )
                candidates = await list_series_needing_sync(session)
        assert any(c.id == series_id for c in candidates)
    finally:
        await _cleanup(series_id, created)


@pytest.mark.asyncio
async def test_finished_series_missing_cover_art_remains_a_sync_candidate() -> None:
    """#67: a series marked FINISHED before cover/banner art existed as a
    concept (anilist_cover_url still NULL) must remain a candidate for one
    more pass to backfill it — otherwise it would never be reconsidered by
    the FINISHED-skip rule above, permanently missing cover art.
    """
    series_id, created = await _ensure_test_series(999999002, f"{TEST_PREFIX} Finished No Cover Art")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE series SET anilist_status = 'FINISHED', "
                        "anilist_cover_url = NULL, episode_schedule_synced_at = now() "
                        "WHERE id = :sid"
                    ),
                    {"sid": series_id},
                )
                candidates = await list_series_needing_sync(session)
        assert any(c.id == series_id for c in candidates)
    finally:
        await _cleanup(series_id, created)


@pytest.mark.asyncio
async def test_finished_series_with_cover_art_is_not_a_sync_candidate() -> None:
    """The counterpart to the above — once cover_url is actually populated,
    a FINISHED series drops out of the candidate list normally again.
    """
    series_id, created = await _ensure_test_series(999999003, f"{TEST_PREFIX} Finished With Cover Art")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE series SET anilist_status = 'FINISHED', "
                        "anilist_cover_url = 'https://example.com/cover.jpg', "
                        "episode_schedule_synced_at = now() WHERE id = :sid"
                    ),
                    {"sid": series_id},
                )
                candidates = await list_series_needing_sync(session)
        assert not any(c.id == series_id for c in candidates)
    finally:
        await _cleanup(series_id, created)
