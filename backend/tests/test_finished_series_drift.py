"""Real-Postgres tests for #175's weekly finished-series drift re-check.

Matches this project's standing testing convention: the database is always
real (never mocked), but the third-party AniList HTTP boundary is fair
game to mock — same "mock the boundary, not the database" split already
used for other outbound-HTTP-adjacent tests in this project (e.g.
test_error_alerting.py's Telegram mock). Unlike test_anilist_sync.py (which
hits the real AniList API against a couple of stable, real ids),
_fetch_finished_series_status and check_finished_series_drift here are
tested against httpx.MockTransport instead — needed specifically to assert
the lightweight query really only requests `status`/`episodes` and never
the heavier fields, which isn't observable against a real response body.
"""

import json

import httpx
import pytest
from sqlalchemy import text

from core.db import async_session_factory
from repositories.series_episode_schedule import (
    clear_drift_flag,
    list_finished_series_for_drift_check,
    set_drift_flag,
)
from services import anilist_sync
from services.anilist_sync import (
    _detect_drift,
    _fetch_finished_series_status,
    check_finished_series_drift,
)

TEST_PREFIX = "__test_175__"


# --- _detect_drift: pure decision function, no DB/network involved --------


def test_no_drift_when_still_finished_and_episode_count_within_baseline() -> None:
    assert (
        _detect_drift(
            live_status="FINISHED",
            live_episode_count=24,
            recorded_episode_count=24,
            max_researched_episode=24,
        )
        is None
    )


def test_status_drift_when_no_longer_finished() -> None:
    assert (
        _detect_drift(
            live_status="RELEASING",
            live_episode_count=24,
            recorded_episode_count=24,
            max_researched_episode=24,
        )
        == "status_drift"
    )


def test_status_drift_takes_priority_over_episode_count_drift() -> None:
    # Both conditions are true at once — status_drift must win, per the
    # issue's own priority ordering (the more fundamental change).
    assert (
        _detect_drift(
            live_status="HIATUS",
            live_episode_count=30,
            recorded_episode_count=24,
            max_researched_episode=24,
        )
        == "status_drift"
    )


def test_episode_count_drift_when_anilist_count_exceeds_recorded_count() -> None:
    assert (
        _detect_drift(
            live_status="FINISHED",
            live_episode_count=25,
            recorded_episode_count=24,
            max_researched_episode=20,
        )
        == "episode_count_drift"
    )


def test_episode_count_drift_when_anilist_count_exceeds_max_researched_episode() -> None:
    # recorded anilist_episode_count is stale/lower than what's actually
    # been researched — the baseline must be the GREATEST of the two, per
    # the issue's own drift definition.
    assert (
        _detect_drift(
            live_status="FINISHED",
            live_episode_count=25,
            recorded_episode_count=20,
            max_researched_episode=24,
        )
        == "episode_count_drift"
    )


def test_no_drift_when_episode_count_equals_baseline_exactly() -> None:
    # Strictly greater-than, not >=.
    assert (
        _detect_drift(
            live_status="FINISHED",
            live_episode_count=24,
            recorded_episode_count=24,
            max_researched_episode=24,
        )
        is None
    )


def test_no_drift_when_live_episode_count_is_none() -> None:
    # The fetch returned a status but AniList's own episodes field was
    # null (e.g. a format quirk) — nothing to compare, no drift from this
    # signal alone.
    assert (
        _detect_drift(
            live_status="FINISHED",
            live_episode_count=None,
            recorded_episode_count=24,
            max_researched_episode=24,
        )
        is None
    )


def test_null_recorded_episode_count_treated_as_zero_baseline() -> None:
    assert (
        _detect_drift(
            live_status="FINISHED",
            live_episode_count=1,
            recorded_episode_count=None,
            max_researched_episode=0,
        )
        == "episode_count_drift"
    )


# --- _fetch_finished_series_status: mocked HTTP boundary -------------------


@pytest.mark.asyncio
async def test_fetch_finished_series_status_requests_only_status_and_episodes() -> None:
    captured_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured_bodies.append(body)
        return httpx.Response(200, json={"data": {"Media": {"status": "FINISHED", "episodes": 24}}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status, episode_count = await _fetch_finished_series_status(client, 12345)

    assert status == "FINISHED"
    assert episode_count == 24
    assert len(captured_bodies) == 1
    assert captured_bodies[0]["variables"] == {"id": 12345}
    query = captured_bodies[0]["query"]
    assert "status" in query
    assert "episodes" in query
    for heavy_field in ("coverImage", "bannerImage", "description", "airingSchedule"):
        assert heavy_field not in query, f"{heavy_field} must not be requested by the lightweight drift check"


@pytest.mark.asyncio
async def test_fetch_finished_series_status_returns_none_none_on_non_200() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        status, episode_count = await _fetch_finished_series_status(client, 12345)
    assert status is None
    assert episode_count is None


@pytest.mark.asyncio
async def test_fetch_finished_series_status_returns_none_none_when_media_missing() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": {"Media": None}}))
    async with httpx.AsyncClient(transport=transport) as client:
        status, episode_count = await _fetch_finished_series_status(client, 999_999_999)
    assert status is None
    assert episode_count is None


# --- Repository: candidate listing + flag set/clear, real Postgres --------


async def _make_series(
    anilist_id: int,
    title: str,
    *,
    status: str | None = "FINISHED",
    episode_count: int | None = None,
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
                            (title, provenance, anilist_id, anilist_status,
                             anilist_episode_count, anilist_drift_reason,
                             anilist_drift_flagged_at)
                        VALUES
                            (:title, 'community', :aid, :status, :episode_count,
                             :reason, CASE WHEN :flagged THEN now() ELSE NULL END)
                        RETURNING id
                        """
                    ),
                    {
                        "title": title,
                        "aid": anilist_id,
                        "status": status,
                        "episode_count": episode_count,
                        "reason": drift_reason,
                        "flagged": drift_flagged,
                    },
                )
            ).scalar_one()
    return series_id


async def _add_researched_episode(series_id: int, episode_number: int) -> None:
    """Minimal citation -> contribution -> episode chain, mirroring
    test_series_episodes.py's own _make_approved_episode helper — only
    max_researched_episode's MAX(episode_number) join needs a real row
    here, nothing else about the episode's content matters for this test.
    """
    async with async_session_factory() as session:
        async with session.begin():
            citation_id = (
                await session.execute(
                    text("INSERT INTO citations (url, description) VALUES (NULL, :d) RETURNING id"),
                    {"d": f"{TEST_PREFIX}citation"},
                )
            ).scalar_one()
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
                {
                    "sid": series_id,
                    "epnum": episode_number,
                    "cid": citation_id,
                    "contrib_id": contribution_id,
                },
            )


async def _cleanup_series(series_id: int) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            citation_ids = [
                row.citation_id
                for row in (
                    await session.execute(
                        text("SELECT citation_id FROM episodes WHERE series_id = :sid"), {"sid": series_id}
                    )
                ).fetchall()
            ]
            await session.execute(text("DELETE FROM episodes WHERE series_id = :sid"), {"sid": series_id})
            await session.execute(text("DELETE FROM contributions WHERE series_id = :sid"), {"sid": series_id})
            if citation_ids:
                await session.execute(
                    text("DELETE FROM citations WHERE id = ANY(:ids)"), {"ids": citation_ids}
                )
            await session.execute(text("DELETE FROM series WHERE id = :sid"), {"sid": series_id})


@pytest.mark.asyncio
async def test_finished_series_is_a_drift_candidate() -> None:
    series_id = await _make_series(999_175_001, f"{TEST_PREFIX} Finished Show")
    try:
        async with async_session_factory() as session:
            candidates = await list_finished_series_for_drift_check(session)
        assert any(c.id == series_id for c in candidates)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_releasing_series_is_not_a_drift_candidate() -> None:
    # #49's own daily loop already covers RELEASING series — this weekly
    # loop's whole reason to exist is the FINISHED case that loop skips.
    series_id = await _make_series(999_175_002, f"{TEST_PREFIX} Releasing Show", status="RELEASING")
    try:
        async with async_session_factory() as session:
            candidates = await list_finished_series_for_drift_check(session)
        assert not any(c.id == series_id for c in candidates)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_never_synced_series_is_not_a_drift_candidate() -> None:
    series_id = await _make_series(999_175_003, f"{TEST_PREFIX} Never Synced Show", status=None)
    try:
        async with async_session_factory() as session:
            candidates = await list_finished_series_for_drift_check(session)
        assert not any(c.id == series_id for c in candidates)
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_candidate_carries_max_researched_episode_from_episodes_table() -> None:
    series_id = await _make_series(
        999_175_004, f"{TEST_PREFIX} Researched Show", episode_count=20
    )
    try:
        await _add_researched_episode(series_id, 22)
        await _add_researched_episode(series_id, 24)  # higher than anilist_episode_count
        async with async_session_factory() as session:
            candidates = await list_finished_series_for_drift_check(session)
        match = next(c for c in candidates if c.id == series_id)
        assert match.max_researched_episode == 24
        assert match.anilist_episode_count == 20
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_candidate_max_researched_episode_defaults_to_zero_with_no_episodes() -> None:
    series_id = await _make_series(999_175_005, f"{TEST_PREFIX} No Episodes Yet")
    try:
        async with async_session_factory() as session:
            candidates = await list_finished_series_for_drift_check(session)
        match = next(c for c in candidates if c.id == series_id)
        assert match.max_researched_episode == 0
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_candidate_carries_previous_drift_reason() -> None:
    series_id = await _make_series(
        999_175_006,
        f"{TEST_PREFIX} Already Flagged Show",
        drift_reason="status_drift",
        drift_flagged=True,
    )
    try:
        async with async_session_factory() as session:
            candidates = await list_finished_series_for_drift_check(session)
        match = next(c for c in candidates if c.id == series_id)
        assert match.previous_drift_reason == "status_drift"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_set_drift_flag_records_timestamp_and_reason() -> None:
    series_id = await _make_series(999_175_007, f"{TEST_PREFIX} To Be Flagged")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await set_drift_flag(session, series_id=series_id, reason="episode_count_drift")
        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT anilist_drift_flagged_at, anilist_drift_reason FROM series WHERE id = :sid"),
                    {"sid": series_id},
                )
            ).one()
        assert row.anilist_drift_flagged_at is not None
        assert row.anilist_drift_reason == "episode_count_drift"
    finally:
        await _cleanup_series(series_id)


@pytest.mark.asyncio
async def test_clear_drift_flag_resolves_a_previously_flagged_series() -> None:
    """The self-resolving case: a series flagged on an earlier cycle is no
    longer drifted on a later one — the flag must be nulled back out, not
    left stale.
    """
    series_id = await _make_series(
        999_175_008,
        f"{TEST_PREFIX} Self Resolving Show",
        drift_reason="status_drift",
        drift_flagged=True,
    )
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await clear_drift_flag(session, series_id=series_id)
        async with async_session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT anilist_drift_flagged_at, anilist_drift_reason FROM series WHERE id = :sid"),
                    {"sid": series_id},
                )
            ).one()
        assert row.anilist_drift_flagged_at is None
        assert row.anilist_drift_reason is None
    finally:
        await _cleanup_series(series_id)


# --- check_finished_series_drift: full cycle, mocked HTTP + real DB -------


@pytest.mark.asyncio
async def test_check_finished_series_drift_full_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """One cycle across three FINISHED series exercising all three real
    outcomes at once: a status-drift flag newly set, an episode-count-
    drift flag newly set, and a previously-flagged series clearing back to
    normal because AniList now agrees with what's already recorded.
    """
    status_drift_id = await _make_series(999_175_101, f"{TEST_PREFIX} Status Drift Show", episode_count=24)
    episode_drift_id = await _make_series(999_175_102, f"{TEST_PREFIX} Episode Drift Show", episode_count=24)
    self_resolved_id = await _make_series(
        999_175_103,
        f"{TEST_PREFIX} Self Resolved Show",
        episode_count=24,
        drift_reason="status_drift",
        drift_flagged=True,
    )
    unrelated_stable_id = await _make_series(
        999_175_104, f"{TEST_PREFIX} Stable Show", episode_count=24
    )

    live_responses = {
        999_175_101: {"status": "HIATUS", "episodes": 24},
        999_175_102: {"status": "FINISHED", "episodes": 26},
        999_175_103: {"status": "FINISHED", "episodes": 24},
        999_175_104: {"status": "FINISHED", "episodes": 24},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        anilist_id = body["variables"]["id"]
        return httpx.Response(200, json={"data": {"Media": live_responses[anilist_id]}})

    # Capture the REAL AsyncClient class before patching — anilist_sync.httpx
    # is the same shared `httpx` module object this test file imports, so
    # patching its .AsyncClient attribute would otherwise make this fake
    # constructor call itself recursively.
    real_async_client = httpx.AsyncClient

    def _fake_async_client(*args, **kwargs) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(anilist_sync.httpx, "AsyncClient", _fake_async_client)
    monkeypatch.setattr(anilist_sync.asyncio, "sleep", _instant_sleep)

    try:
        changed = await check_finished_series_drift()
        # 3 of the 4 series' drift STATE actually changed this cycle (the
        # stable show's state — no flag before, no flag after — did not).
        assert changed == 3

        async with async_session_factory() as session:
            rows = {
                row.id: row
                for row in (
                    await session.execute(
                        text(
                            "SELECT id, anilist_drift_reason, anilist_drift_flagged_at "
                            "FROM series WHERE id = ANY(:ids)"
                        ),
                        {
                            "ids": [
                                status_drift_id,
                                episode_drift_id,
                                self_resolved_id,
                                unrelated_stable_id,
                            ]
                        },
                    )
                ).fetchall()
            }

        assert rows[status_drift_id].anilist_drift_reason == "status_drift"
        assert rows[status_drift_id].anilist_drift_flagged_at is not None

        assert rows[episode_drift_id].anilist_drift_reason == "episode_count_drift"
        assert rows[episode_drift_id].anilist_drift_flagged_at is not None

        # Self-resolving case: previously flagged, now confirmed FINISHED
        # with a matching episode count — cleared back to NULL.
        assert rows[self_resolved_id].anilist_drift_reason is None
        assert rows[self_resolved_id].anilist_drift_flagged_at is None

        # Never flagged, still not flagged.
        assert rows[unrelated_stable_id].anilist_drift_reason is None
        assert rows[unrelated_stable_id].anilist_drift_flagged_at is None
    finally:
        for sid in (status_drift_id, episode_drift_id, self_resolved_id, unrelated_stable_id):
            await _cleanup_series(sid)


async def _instant_sleep(_seconds: float) -> None:
    """Replaces the real _REQUEST_DELAY_SECONDS pacing sleep in the full-
    cycle test above — this test isn't exercising rate-limit pacing, so
    there's no reason for it to actually take several real seconds.
    """
    return None
