"""Raw SQL for #49's AniList episode/air-date sync. series_episode_schedule
is deliberately separate from episodes (repositories/episodes.py) — this
table only ever records "does episode N exist and when did it air,"
independent of any filler/canon research.
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def list_series_needing_sync(session: AsyncSession) -> list[Row]:
    """A series already confirmed FINISHED from a previous sync doesn't
    need re-checking every run — only RELEASING (or never-synced, NULL)
    series are re-fetched, so a finished show's schedule stops costing
    outbound AniList calls entirely once it's confirmed done.

    Exception: a FINISHED series still missing cover/banner art (#67 —
    added after some series were already marked FINISHED by an earlier
    sync, so they'd otherwise never be reconsidered by the check above)
    remains a candidate for exactly one more pass, purely to backfill
    that field. Once populated it drops out again like anything else.

    #126: same one-more-pass exception for anilist_description — a series
    already marked FINISHED and cover-synced before this field existed
    would otherwise never be revisited to backfill it. Once populated it
    drops out of the candidate list again, same as the cover-art case.
    """
    result = await session.execute(
        text(
            """
            SELECT id, anilist_id
            FROM series
            WHERE anilist_id IS NOT NULL
              AND (
                anilist_status IS NULL
                OR anilist_status != 'FINISHED'
                OR anilist_cover_url IS NULL
                OR anilist_description IS NULL
              )
            ORDER BY id
            """
        )
    )
    return list(result.fetchall())


async def upsert_schedule(
    session: AsyncSession, *, series_id: int, episodes: list[tuple[int, int]]
) -> None:
    """episodes: (episode_number, airing_at unix timestamp) pairs."""
    for episode_number, airing_at in episodes:
        await session.execute(
            text(
                """
                INSERT INTO series_episode_schedule (series_id, episode_number, aired_at)
                VALUES (:series_id, :episode_number, to_timestamp(:airing_at))
                ON CONFLICT (series_id, episode_number) DO UPDATE SET
                    aired_at = EXCLUDED.aired_at
                """
            ),
            {"series_id": series_id, "episode_number": episode_number, "airing_at": airing_at},
        )


async def list_finished_series_for_drift_check(session: AsyncSession) -> list[Row]:
    """#175: every series AniList has ever reported FINISHED — the
    candidate set for the weekly drift-recheck loop, independent of
    list_series_needing_sync() above (which actively EXCLUDES these once
    FINISHED, by design, for the daily sync).

    max_researched_episode is this project's own highest researched
    episode number for the series (episodes.episode_number), used
    alongside anilist_episode_count to compute the "known baseline" a
    freshly-fetched AniList episode count is compared against — a series
    can have more AniList-known episodes than this project has actually
    researched yet, which is real drift even if anilist_episode_count
    itself is already stale/lower.

    previous_drift_reason is included so the caller can tell whether this
    cycle's result is actually a STATE CHANGE (newly flagged, newly
    cleared, or the reason itself changed) versus confirming an
    already-known state — used only for the cycle's own return-count/log
    line, never for the drift decision itself.
    """
    result = await session.execute(
        text(
            """
            SELECT s.id,
                   s.anilist_id,
                   s.anilist_episode_count,
                   s.anilist_drift_reason AS previous_drift_reason,
                   COALESCE(MAX(e.episode_number), 0) AS max_researched_episode
            FROM series s
            LEFT JOIN episodes e ON e.series_id = s.id
            WHERE s.anilist_status = 'FINISHED'
              AND s.anilist_id IS NOT NULL
            GROUP BY s.id, s.anilist_id, s.anilist_episode_count, s.anilist_drift_reason
            ORDER BY s.id
            """
        )
    )
    return list(result.fetchall())


async def set_drift_flag(session: AsyncSession, *, series_id: int, reason: str) -> None:
    """reason: 'status_drift' | 'episode_count_drift' — see schema.sql's
    CHECK constraint on series.anilist_drift_reason.
    """
    await session.execute(
        text(
            """
            UPDATE series
            SET anilist_drift_flagged_at = now(),
                anilist_drift_reason = :reason
            WHERE id = :series_id
            """
        ),
        {"series_id": series_id, "reason": reason},
    )


async def clear_drift_flag(session: AsyncSession, *, series_id: int) -> None:
    """A later re-check found the series is no longer drifted (e.g.
    AniList briefly glitched then reported FINISHED again) — clears a
    previously-set flag back to NULL rather than leaving it stale. A
    no-op (0 rows changed meaningfully) if the series wasn't flagged.
    """
    await session.execute(
        text(
            """
            UPDATE series
            SET anilist_drift_flagged_at = NULL,
                anilist_drift_reason = NULL
            WHERE id = :series_id
            """
        ),
        {"series_id": series_id},
    )


async def mark_synced(
    session: AsyncSession,
    *,
    series_id: int,
    anilist_status: str,
    anilist_episode_count: int | None,
    anilist_cover_url: str | None,
    anilist_banner_url: str | None,
    anilist_description: str | None = None,
    anilist_start_date: date | None = None,
    anilist_end_date: date | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE series
            SET anilist_status = :status,
                anilist_episode_count = :episode_count,
                anilist_cover_url = :cover_url,
                anilist_banner_url = :banner_url,
                anilist_description = :description,
                anilist_start_date = :start_date,
                anilist_end_date = :end_date,
                episode_schedule_synced_at = now()
            WHERE id = :series_id
            """
        ),
        {
            "status": anilist_status,
            "episode_count": anilist_episode_count,
            "cover_url": anilist_cover_url,
            "banner_url": anilist_banner_url,
            "description": anilist_description,
            "start_date": anilist_start_date,
            "end_date": anilist_end_date,
            "series_id": series_id,
        },
    )
