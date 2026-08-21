# Migrations

Numbered SQL files for upgrading an already-running database, matching
`Napandee/AniDex`'s convention (`001_add_x.sql`, `002_y.sql`, ...). Applied
by hand against the live Postgres instance, not part of the deploy
pipeline — see `CLAUDE.md`'s Guardrails ("Ask before any schema migration
that could drop or alter existing columns/data").

`../schema.sql` is the fresh-install target schema. This directory is
empty as of the v1 schema — no upgrades have been needed yet.
