from typing import Literal

from pydantic import BaseModel


class AniListLookupOut(BaseModel):
    """#165: response for GET /api/v1/anilist-lookup/{anilist_id} — the
    series-proposal form's blur-triggered lookup on the anilist_id field.

    Three mutually exclusive outcomes via `status`, all returned as a
    normal 200 (none of these is an error — "not found"/"already exists"
    are both legitimate, expected results for a live user-facing lookup):

    - "already_exists": the id already belongs to a live `series` row —
      existing_series_id/slug/title are populated, format/episode_count/
      cover_image_url are not (no AniList call was even made, see
      services/anilist_lookup.py).
    - "found": a real, not-yet-catalogued AniList entry — title/format/
      episode_count/cover_image_url are populated, existing_series_* are
      not.
    - "not_found": no such AniList id, or AniList couldn't be reached —
      every field beyond status/anilist_id is null.
    """

    status: Literal["found", "already_exists", "not_found"]
    anilist_id: int
    title: str | None = None
    format: str | None = None
    episode_count: int | None = None
    cover_image_url: str | None = None
    existing_series_id: int | None = None
    existing_series_slug: str | None = None
