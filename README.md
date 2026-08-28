# AniFillerPedia

An open, community-editable database of anime filler/canon episode data —
which episodes you can skip without missing manga-original story, and which
ones you can't.

No official source publishes this in a genuinely open, freely-reusable way.
The closest existing option, animefillerlist.com, has no API — and
animefillerlist.tv (a separate, much newer site, not the same operator)
has terms that explicitly forbid scraping; the closest API-accessible
option (Simkl) restricts catalog access to apps that also integrate
Simkl's own tracking/sync. This project exists to be the thing that
doesn't have either problem: openly licensed data, a real API, no
login/sync requirement to use it, and community correction built in from
day one — closer to Wikipedia's model than a commercial tracker's.

**Live:** [anifillerpedia.wiki](https://anifillerpedia.wiki) ·
[API docs](docs/API.md) · [Contributing](CONTRIBUTING.md)

## Status

Both the API and the public frontend are live and feature-complete: public
read API, GitHub/Discord auth, anonymous or signed-in submissions
(single-episode or, for a logged-in contributor with a full breakdown in
hand, a whole range of episodes at once), moderator review, community
trust-weighted voting with auto-approval, bulk export, and full test
coverage against a real Postgres instance. The Astro frontend covers
browsing/search, a per-series canon/filler/mixed dashboard, every
contribution/proposal flow, a moderation queue, and admin user management —
the API isn't the only way in.

Also shipped: UI translated across 5 languages (English, Spanish, Hindi,
Japanese, Simplified Chinese) via path-based locale routing, a live
"airing" status badge for still-releasing shows, slug-based series URLs,
a series description/era-tile overview on the series detail page,
within-franchise watch-next/previous navigation for series split across
multiple AniList entries, and production monitoring with Telegram
alerting.

The dataset itself is real, cited, hand-compiled research (not scraped
from any single restricted source), targeted using the open-licensed "has
fillers" tag from
[manami-project/anime-offline-database](https://github.com/manami-project/anime-offline-database).
Well over 100 series are fully loaded (check `GET /api/v1/series` for the
live, current count — the catalog keeps growing, so a fixed number here
would just go stale again). More shows are queued behind these — the
catalog itself also grows through community series proposals, not just
this initial batch.

## Features

- **Per-episode filler/canon/mixed status** — not just "this show has
  filler," which episode numbers specifically, each with a source citation.
- **Public read API** — no account, no auth, no rate-limit wall for
  reasonable use. See [docs/API.md](docs/API.md).
- **Community correction workflow** — submit corrections anonymously or
  signed in; changes go live via moderator approval or community
  trust-weighted voting. See [CONTRIBUTING.md](CONTRIBUTING.md).
- **Source citations per entry** — every filler/canon claim traceable to
  where it came from, so the dataset stays auditable. A citation also
  carries how many independent sources agree, surfaced as a corroboration
  badge, with the fuller research trail available behind a disclosure
  rather than cluttering the main claim.

## Repo layout

Monorepo, hard split between `backend/` (FastAPI/Python) and `frontend/`
(Astro/Node) — kept genuinely separate (no shared config/tooling, path-
filtered CI) so either side can be worked on and deployed independently.
See each directory's own `README.md` for local setup.

## License

- **Data**: [CC BY-NC-SA 4.0](DATA_LICENSE) — free to read and reuse,
  including by other trackers, with attribution; a paid product needs a
  separate commercial agreement to use it as a backing data source. See
  `DATA_LICENSE` for the full terms and commercial-licensing contact, or
  query it live at `GET /api/v1/license`.
- **Code**: [MIT](LICENSE).
