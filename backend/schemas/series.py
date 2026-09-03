from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SeriesOut(BaseModel):
    # Fields with a validation_alias otherwise only accept that alias as
    # input — populate_by_name lets **row._mapping (raw SQL column names)
    # and a plain keyword construction (e.g. in tests) both keep working.
    model_config = ConfigDict(populate_by_name=True)

    id: int
    anilist_id: int | None
    mal_id: int | None
    anidb_id: int | None
    title: str
    provenance: str
    created_at: datetime
    # #116: slug-based series URLs (/series/berserk instead of /series/8).
    # Nullable only until the one-time production backfill runs — every
    # series created after #116 shipped always has one (repositories/
    # series.py's create() generates it at insert time).
    slug: str | None
    # #46 follow-up (2026-08-22): synced by #49's worker on a daily cadence,
    # not fetched live from AniList per-request — a real AniList outage
    # previously took down cover art site-wide since it used to be a
    # synchronous third-party dependency on every page load. Null until
    # the sync worker has reached this series at least once.
    cover_image_url: str | None = Field(validation_alias="anilist_cover_url")
    banner_image_url: str | None = Field(validation_alias="anilist_banner_url")
    # #111: AniList's own MediaStatus enum (FINISHED, RELEASING,
    # NOT_YET_RELEASED, CANCELLED, HIATUS), synced by #49's daily worker —
    # same null-until-first-sync convention as the cover/banner URLs above.
    # Surfaces whether a series is still airing, not yet aired, or done.
    airing_status: str | None = Field(validation_alias="anilist_status")
    # #133: within-franchise watch-order position (e.g. Fairy Tail=1,
    # Fairy Tail (2014)=2, ...). Column name matches directly, no alias
    # needed. Null for the vast majority of series (standalone, or no
    # decided watch order yet). #146: search_series() (both the plain list
    # and recently_updated branches) DOES select this column, same as
    # get_related_series/get_series_by_identifier — an earlier version of
    # this comment claimed the list omitting it was deliberate, matching
    # #126's description/dates, but that was actually just an oversight
    # (#146) with no real reason behind it, unlike #126's genuinely
    # intentional detail-only fields. The default is kept anyway as cheap
    # defensive robustness for any future row shape that doesn't carry it.
    sequence_order: int | None = None


class SeriesDetailOut(SeriesOut):
    synonyms: list[str]
    # #49's AniList sync — the real total episode count, independent of how
    # many of them have actually been hand-researched (episodes.py's own
    # count). Null until #49's worker has synced this series at least once.
    anilist_episode_count: int | None
    # Lightweight links to other catalog entries covering the same show
    # split across multiple real AniList entries (e.g. Fairy Tail /
    # Fairy Tail (2014) / Fairy Tail (2018)) — see series_relations in
    # schema.sql. Empty for the vast majority of series.
    related_series: list[SeriesOut]
    # #126: AniList's own synopsis + air-date range, synced by #49's
    # worker on the same cadence as everything else — null until first
    # sync (or, for description, until a still-pending #67-style
    # one-more-pass backfill for a series marked FINISHED before this
    # field existed; see repositories/series_episode_schedule.py). Only
    # exposed on the detail response (not SeriesOut/the browse grid) —
    # the about-card/era-tile only render on the series detail page.
    description: str | None = Field(validation_alias="anilist_description")
    start_date: date | None = Field(validation_alias="anilist_start_date")
    end_date: date | None = Field(validation_alias="anilist_end_date")
    # #133: the adjacent entries in this series' own series_relations group,
    # by sequence_order — computed in services/series.py's get_series(),
    # not the repository layer (needs both the current series' own
    # sequence_order and the related_series list together). None when this
    # series has no sequence_order, or no related entries with one —
    # renders nothing on the frontend, matching this page's existing
    # "no placeholder" convention (see #51).
    next_series: SeriesOut | None
    previous_series: SeriesOut | None


class SeriesListOut(BaseModel):
    items: list[SeriesOut]
    total: int
    limit: int
    offset: int


class NeedsResearchItem(BaseModel):
    """#153: one row of the public "needs research" queue — a series with
    zero episode rows (`never_researched`), or a series #175's weekly
    drift worker has flagged as no longer matching AniList's live state
    (`status_drift` / `episode_count_drift`, read straight from
    `series.anilist_drift_reason` rather than re-derived here). The
    issue's own scope note guarantees these two cases never overlap: a
    drift-flagged series always has episodes to have drifted from, so a
    row is always exactly one reason, never both.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: int
    title: str
    slug: str | None
    reason: str
    # Null for a never_researched series that's also never been synced by
    # #49's daily worker yet; populated whenever AniList has been checked
    # at least once, regardless of which reason this row carries.
    anilist_episode_count: int | None
    airing_status: str | None = Field(validation_alias="anilist_status")
    researched_episode_count: int


class NeedsResearchListOut(BaseModel):
    items: list[NeedsResearchItem]
    total: int
    limit: int
    offset: int
