# AniFillerPedia

An open, community-editable database of anime filler/canon episode data —
which episodes you can skip without missing manga-original story, and which
ones you can't.

No official source publishes this in a genuinely open, freely-reusable way.
The closest existing option (animefillerlist.com) has no API and terms that
forbid scraping; the closest API-accessible option (Simkl) restricts catalog
access to apps that also integrate Simkl's own tracking/sync. This project
exists to be the thing that doesn't have either problem: openly licensed data,
a real API, no login/sync requirement to use it, and community
correction built in from day one — closer to Wikipedia's model than a
commercial tracker's.

## Status

Early — not yet built. Currently bootstrapping an initial dataset for a
defined set of well-known long-running shows via hand-compiled, cited research
(not scraped from any single restricted source), starting from the
open-licensed "has fillers" tag already present in
[manami-project/anime-offline-database](https://github.com/manami-project/anime-offline-database)
as a targeting signal for which shows to research first.

## Features (planned)

- **Per-episode filler/canon/mixed status** — not just "this show has filler,"
  which episode numbers specifically.
- **Public read API** — no account, no auth, no rate-limit wall for reasonable
  use.
- **Community correction workflow** — submit/adjust/correct entries with an
  approval flow, not open write access to everyone.
- **Source citations per entry** — every filler/canon claim traceable to where
  it came from, so the dataset itself stays auditable.

## License

- **Data**: [Open Database License (ODbL) v1.0](DATA_LICENSE) — free to reuse,
  share, and build on, with attribution and share-alike requirements. Matches
  the license of manami-project/anime-offline-database, one of this project's
  own seed sources.
- **Code**: [MIT](LICENSE) — the server/tooling, once it exists.
