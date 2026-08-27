"""#80: parses the community's own existing shorthand for episode ranges
("1-44, 48-49, 52-53") into episode-number sets — the exact notation
already used throughout this project's hand-compiled research (see
data/bootstrap/*.json's own sourcing) and the natural format a contributor
pasting a Reddit/AniList-community breakdown already has in hand.

Kept as pure functions, no DB access — easy to unit-test and reusable from
a dry-run preview without touching the database.
"""

import re

_RANGE_PART = re.compile(r"^(\d+)(?:-(\d+))?$")

MAX_BATCH_SIZE = 2000


class RangeParseError(Exception):
    """Raised for malformed input the caller couldn't have produced by
    accident from a real range list — a genuinely wrong paste, not just an
    empty field."""


def parse_ranges(raw: str) -> set[int]:
    """"1-5, 8, 10-12" -> {1,2,3,4,5,8,10,11,12}. Empty/whitespace-only
    input is a valid "nothing in this category" and returns an empty set,
    not an error — not every submission has all three categories.
    """
    raw = raw.strip()
    if not raw:
        return set()

    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        match = _RANGE_PART.match(part)
        if not match:
            raise RangeParseError(f"Could not parse {part!r} as an episode number or range")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < start:
            raise RangeParseError(f"Invalid range {part!r}")
        # Security review (#89): reject an oversized segment BEFORE
        # materializing it — "1-999999999999" would otherwise build a
        # billion-plus-entry set right here, well before parse_and_
        # validate's own combined MAX_BATCH_SIZE check ever runs. No
        # single segment can legitimately need to exceed the whole
        # batch's own cap, so bounding here is exact, not approximate.
        if end - start + 1 > MAX_BATCH_SIZE:
            raise RangeParseError(
                f"Range {part!r} spans {end - start + 1} episodes, "
                f"more than the {MAX_BATCH_SIZE}-episode batch limit"
            )
        result.update(range(start, end + 1))
    return result


class BulkRangeValidationError(Exception):
    """Carries a structured detail dict, same shape the router turns
    straight into a 422 response body."""

    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(str(detail))


def parse_and_validate(
    canon_ranges: str, mixed_ranges: str, filler_ranges: str
) -> dict[int, str]:
    """Returns {episode_number: status}. Raises BulkRangeValidationError
    (never silently drops or guesses) for:
    - malformed input in any of the three fields
    - an episode number declared in more than one category — a genuine
      self-contradiction, not a moderation decision
    - a combined batch bigger than MAX_BATCH_SIZE
    - nothing declared at all across all three fields
    """
    try:
        canon = parse_ranges(canon_ranges)
        mixed = parse_ranges(mixed_ranges)
        filler = parse_ranges(filler_ranges)
    except RangeParseError as exc:
        raise BulkRangeValidationError({"message": str(exc)}) from exc

    overlaps = {
        "canon_mixed": sorted(canon & mixed),
        "canon_filler": sorted(canon & filler),
        "mixed_filler": sorted(mixed & filler),
    }
    real_overlaps = {k: v for k, v in overlaps.items() if v}
    if real_overlaps:
        raise BulkRangeValidationError(
            {
                "message": (
                    "The same episode number appears in more than one category — "
                    "fix the overlap before submitting."
                ),
                "overlaps": real_overlaps,
            }
        )

    by_episode = {ep: "canon" for ep in canon}
    by_episode.update({ep: "mixed" for ep in mixed})
    by_episode.update({ep: "filler" for ep in filler})

    if not by_episode:
        raise BulkRangeValidationError(
            {"message": "No episodes declared — fill in at least one of canon/mixed/filler."}
        )

    if len(by_episode) > MAX_BATCH_SIZE:
        raise BulkRangeValidationError(
            {
                "message": f"Batch too large: {len(by_episode)} episodes declared, max is {MAX_BATCH_SIZE}.",
                "declared_count": len(by_episode),
                "max_batch_size": MAX_BATCH_SIZE,
            }
        )

    return by_episode


def find_out_of_range_episodes(
    episode_numbers, anilist_episode_count: int | None  # noqa: ANN001 - Iterable[int]
) -> list[int]:
    """#152: which of the given episode numbers exceed the series' own
    known real episode count (series.anilist_episode_count, synced by
    #49's AniList worker). A NULL count — a series #49 has never synced
    (a brand-new community proposal, a movie/special with no AniList
    entry) — means "unknown," not "zero episodes": validation is a no-op
    in that case, never a block, per this project's own guardrail against
    rejecting a submission just because the real count isn't known yet.
    Pure function, no DB access, same reasoning as parse_ranges/
    parse_and_validate above — easy to unit test, reusable from both the
    single-episode and bulk submission paths.
    """
    if anilist_episode_count is None:
        return []
    return sorted(n for n in episode_numbers if n > anilist_episode_count)
