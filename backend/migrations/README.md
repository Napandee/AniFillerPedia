# Migrations

Numbered SQL files for upgrading an already-running database, matching
`Napandee/AniDex`'s convention (`001_add_x.sql`, `002_y.sql`, ...). Applied
by hand against the live Postgres instance, not part of the deploy
pipeline — see `CLAUDE.md`'s Guardrails ("Ask before any schema migration
that could drop or alter existing columns/data").

`../schema.sql` is the fresh-install target schema — a new deploy applies it
directly and never touches this directory. This directory holds every
additive change made since the v1 schema shipped (`001_...` through
`021_add_local_auth.sql` as of this writing), applied by hand against
production one at a time as each was merged; `schema.sql` itself is kept in
sync so it always reflects the current, fully-migrated shape. Numbering is
sequential across the whole project's history, not per-feature — check the
highest existing number before adding the next one.
