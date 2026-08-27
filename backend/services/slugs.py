"""Shared slug-generation for series (#116, slug-based series URLs). Used
by both the one-time production backfill (migrations/011_backfill_series_slugs.py)
and repositories/series.py's create() (new series minted via an approved
series_proposals row) so the exact same rule applies whether a slug is
generated for an already-existing series or a brand-new one — no
duplicated logic to drift apart.

Slugs are derived from title: lowercased, non-alphanumeric runs collapsed
to a single hyphen, leading/trailing hyphens stripped (e.g. "Bishoujo
Senshi Sailor Moon R" -> "bishoujo-senshi-sailor-moon-r"). Two different
titles can theoretically collapse to the same base slug even though
today's titles happen to already be distinct strings (e.g. "Fairy Tail" /
"Fairy Tail (2014)" / "Fairy Tail (2018)" all differ, but a hypothetical
"Naruto!" and "Naruto?" wouldn't) — callers disambiguate a collision by
appending the series' own numeric id, which is always unique by
construction.
"""

import re


def slugify_title(title: str) -> str:
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "series"


def disambiguate_slug(base_slug: str, series_id: int) -> str:
    return f"{base_slug}-{series_id}"
