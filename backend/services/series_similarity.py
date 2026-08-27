"""#150: title-similarity duplicate-series detection for the series-
proposal submission flow.

A submitted proposal's anilist_id/mal_id/anidb_id are all optional, and
the frontend's own hint text tells submitters "No lookup/autocomplete
yet, just plain numbers" — so the realistic submission is a bare title
with no ID at all (e.g. "Naruto"). Postgres's UNIQUE constraint on
series.anilist_id/mal_id/anidb_id never fires in that case (NULL !=
NULL), which is exactly the gap repositories/series_proposals.py's own
header comment got wrong about "duplicates are sorted out at review
time" — that's only true when an ID collides.

Deliberately NOT pg_trgm/fuzzy matching: the catalog is a few hundred
rows, and the realistic near-duplicate shapes (case/punctuation/
whitespace differences, or one title being a superstring of another —
e.g. "Naruto" vs "Naruto: Shippuuden") are all caught by a plain
normalized-string comparison with zero extra infrastructure. This
matches the issue's own guidance to lean toward the simpler approach
first, and this project's general bias against building for demand that
isn't proven yet. Revisit with pg_trgm only if real false negatives
actually show up in practice.
"""

import re

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Below this length a normalized title is too short/generic (e.g. "K",
# "Go") for substring containment to mean anything on its own — an EXACT
# match still counts regardless of length, but containment matching is
# skipped for anything shorter than this.
MIN_SUBSTRING_MATCH_LENGTH = 3

# Cap on how many possible matches are ever surfaced at once — this is a
# "heads up, take a look" hint, not a search results page.
MAX_MATCHES = 5


def normalize_title(title: str) -> str:
    """Lowercase, punctuation-stripped, whitespace-collapsed comparison
    key. "Naruto: Shippuuden!" and "naruto   shippuuden" normalize to the
    same string; a fully-punctuation/whitespace title normalizes to "".
    """
    lowered = title.lower()
    collapsed = _NON_ALNUM_RE.sub(" ", lowered)
    return " ".join(collapsed.split())


async def find_similar_series(session: AsyncSession, title: str) -> list[Row]:
    """Returns up to MAX_MATCHES existing `series` rows (id, title, slug)
    whose normalized title either exactly matches the candidate title, or
    contains/is contained by it. Exact matches sort first; ties are
    broken by how close the raw title lengths are (closer first).

    Fetches the whole `series` table and normalizes in Python rather than
    pushing this into SQL — the catalog is small enough (a few hundred
    rows, see module docstring) that this costs nothing that matters, and
    keeps the matching logic somewhere easy to unit-test directly.
    """
    normalized = normalize_title(title)
    if not normalized:
        return []

    rows = (await session.execute(text("SELECT id, title, slug FROM series"))).fetchall()

    scored: list[tuple[int, int, Row]] = []
    for row in rows:
        candidate = normalize_title(row.title)
        if not candidate:
            continue
        if candidate == normalized:
            scored.append((0, abs(len(row.title) - len(title)), row))
        elif (
            len(normalized) >= MIN_SUBSTRING_MATCH_LENGTH
            and len(candidate) >= MIN_SUBSTRING_MATCH_LENGTH
            and (normalized in candidate or candidate in normalized)
        ):
            scored.append((1, abs(len(row.title) - len(title)), row))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in scored[:MAX_MATCHES]]
