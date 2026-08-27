"""Raw SQL for the series catalog. Search matches title AND series_synonyms
— the whole reason #4 captured synonyms during the one-shot bootstrap
import was so search could match alternate/native-script titles, not just
the canonical one (CLAUDE.md Decisions Made).
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from services.slugs import disambiguate_slug, slugify_title


async def search_series(
    session: AsyncSession,
    q: str | None,
    anilist_id: int | None,
    mal_id: int | None,
    anidb_id: int | None,
    limit: int,
    offset: int,
    sort: str | None = None,
) -> tuple[list[Row], int]:
    where = []
    params: dict = {"limit": limit, "offset": offset}

    if q:
        where.append(
            "(s.title ILIKE :q OR EXISTS ("
            "SELECT 1 FROM series_synonyms syn "
            "WHERE syn.series_id = s.id AND syn.synonym ILIKE :q))"
        )
        params["q"] = f"%{q}%"
    if anilist_id is not None:
        where.append("s.anilist_id = :anilist_id")
        params["anilist_id"] = anilist_id
    if mal_id is not None:
        where.append("s.mal_id = :mal_id")
        params["mal_id"] = mal_id
    if anidb_id is not None:
        where.append("s.anidb_id = :anidb_id")
        params["anidb_id"] = anidb_id

    # #47: a plain browse (no q/anilist_id/mal_id/anidb_id) excludes series
    # with zero episode rows — most of the 180 manami-bootstrap catalog
    # entries have never been researched, and showing an empty "no episodes
    # yet" page for the majority of results made the site look broken
    # rather than sparse. A TARGETED lookup (q, or any external id) still
    # returns them: hiding a catalog entry a visitor is specifically
    # searching for would just make them file a duplicate series proposal
    # for something that already exists, unresearched — the actual goal is
    # decluttering the default grid, not making these entries unfindable.
    is_targeted_lookup = bool(where)
    if not is_targeted_lookup:
        # Aliased `ep`, not `e` — the recently_updated branch below already
        # LEFT JOINs episodes as `e`; this WHERE clause is shared by both
        # branches, and a distinct alias avoids relying on subquery scoping
        # to keep the two apart.
        where.append("EXISTS (SELECT 1 FROM episodes ep WHERE ep.series_id = s.id)")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    # Total count is unaffected by sort mode — same WHERE, no join/group.
    total = (
        await session.execute(
            text(f"SELECT count(*) FROM series s {where_sql}"), params
        )
    ).scalar_one()

    if sort == "recently_updated":
        # #42: series has no updated_at of its own — "recently updated"
        # means "most recently had an episode approved." LEFT JOIN so a
        # series with zero episodes still appears (NULLS LAST sorts it
        # after everything with real activity, rather than dropping it).
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT s.id, s.anilist_id, s.mal_id, s.anidb_id, s.title,
                           s.provenance, s.created_at, s.anilist_cover_url, s.anilist_banner_url,
                           s.anilist_status, s.slug, s.sequence_order
                    FROM series s
                    LEFT JOIN episodes e ON e.series_id = s.id
                    {where_sql}
                    GROUP BY s.id
                    ORDER BY MAX(e.updated_at) DESC NULLS LAST, s.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        ).fetchall()
    else:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT s.id, s.anilist_id, s.mal_id, s.anidb_id, s.title,
                           s.provenance, s.created_at, s.anilist_cover_url, s.anilist_banner_url,
                           s.anilist_status, s.slug, s.sequence_order
                    FROM series s
                    {where_sql}
                    ORDER BY s.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        ).fetchall()

    return list(rows), total


async def get_series_by_identifier(session: AsyncSession, identifier: str) -> Row | None:
    """#116: `identifier` is either a numeric series id (legacy/internal
    lookups, e.g. episode/contribution rows that only carry series_id) or
    a slug (the new canonical public URL segment). The check happens in
    Python, not SQL — `WHERE id = :id OR slug = :slug` would also match a
    slug that happens to be all-digits some day, which isn't the intent
    here (an identifier that parses as a plain int is ALWAYS treated as an
    id, never as a slug lookup).
    """
    column = "id" if identifier.isdigit() else "slug"
    result = await session.execute(
        text(
            "SELECT id, anilist_id, mal_id, anidb_id, title, provenance, created_at, "
            "anilist_episode_count, anilist_cover_url, anilist_banner_url, anilist_status, slug, "
            # #126: description/start_date/end_date only fetched on the
            # detail lookup — the browse/search list (search_series above)
            # deliberately doesn't carry these, since the about-card/
            # era-tile only ever render on the series detail page.
            "anilist_description, anilist_start_date, anilist_end_date, "
            # #133: needed here so the service layer knows the CURRENT
            # series' own watch-order position, to compute next/previous
            # against its related_series group.
            "sequence_order "
            f"FROM series WHERE {column} = :identifier"
        ),
        {"identifier": int(identifier) if column == "id" else identifier},
    )
    return result.first()


async def get_synonyms(session: AsyncSession, series_id: int) -> list[str]:
    result = await session.execute(
        text("SELECT synonym FROM series_synonyms WHERE series_id = :id ORDER BY id"),
        {"id": series_id},
    )
    return [row.synonym for row in result.fetchall()]


async def get_related_series(session: AsyncSession, series_id: int) -> list[Row]:
    result = await session.execute(
        text(
            """
            SELECT s.id, s.anilist_id, s.mal_id, s.anidb_id, s.title,
                   s.provenance, s.created_at, s.anilist_cover_url, s.anilist_banner_url,
                   s.anilist_status, s.slug, s.sequence_order
            FROM series_relations r
            JOIN series s ON s.id = r.related_series_id
            WHERE r.series_id = :id
            -- #133: watch order, when populated, rather than insertion
            -- order — services/series.py's get_series() also relies on
            -- these rows carrying sequence_order to compute next/previous.
            ORDER BY s.sequence_order NULLS LAST, s.id
            """
        ),
        {"id": series_id},
    )
    return list(result.fetchall())


async def create(
    session: AsyncSession,
    *,
    title: str,
    anilist_id: int | None,
    mal_id: int | None,
    anidb_id: int | None,
    provenance: str,
    added_by: int | None,
) -> Row:
    """#13: promote an approved series_proposal into the live series
    catalog. anilist_id/mal_id/anidb_id are UNIQUE but nullable — a
    proposal whose external ID collides with an already-bootstrapped
    series raises IntegrityError, which the service layer (not this
    repository) turns into a clean 409 rather than a raw 500.

    #116: also generates a slug for the new row, same rule as the one-time
    production backfill (migrations/011_backfill_series_slugs.py) — both
    import services.slugs so the two can never drift apart. The new row's
    own id is only known after INSERT, so a real collision (the generated
    base slug already belongs to another series) is disambiguated with a
    follow-up UPDATE rather than computed up front.
    """
    result = await session.execute(
        text(
            """
            INSERT INTO series (title, anilist_id, mal_id, anidb_id, provenance, added_by)
            VALUES (:title, :anilist_id, :mal_id, :anidb_id, :provenance, :added_by)
            RETURNING *
            """
        ),
        {
            "title": title,
            "anilist_id": anilist_id,
            "mal_id": mal_id,
            "anidb_id": anidb_id,
            "provenance": provenance,
            "added_by": added_by,
        },
    )
    row = result.one()

    base_slug = slugify_title(title)
    collision = (
        await session.execute(
            text("SELECT 1 FROM series WHERE slug = :slug AND id != :id"),
            {"slug": base_slug, "id": row.id},
        )
    ).first()
    slug = disambiguate_slug(base_slug, row.id) if collision else base_slug
    await session.execute(
        text("UPDATE series SET slug = :slug WHERE id = :id"),
        {"slug": slug, "id": row.id},
    )
    row = (await session.execute(text("SELECT * FROM series WHERE id = :id"), {"id": row.id})).one()
    return row
