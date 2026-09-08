# Data Sources

Where catalogue and episode data comes from, and the rules for importing it.

No single upstream system of record (unlike AniDex, which treats AniList as
its system of record). This project's data is bootstrapped from multiple
legitimate sources, deliberately not from one restricted site:

- **Series-level targeting signal**: the `"has fillers"` / `"canon filler"`
  tags in [manami-project/anime-offline-database](https://github.com/manami-project/anime-offline-database)
  (ODbL-licensed, genuinely open) — used to identify *which* shows are worth
  researching in detail, not as a source of per-episode data (it has none).
  **One-time bootstrap import only, not a live dependency**: confirmed
  2026-08-20 that the upstream repo is archived (last release `2026-27`,
  2026-07-04) — the ODbL license means the last snapshot stays permanently
  reusable, but there's no active maintainer to keep pulling updates from.
  The `series` catalog is seeded once from that snapshot and grows afterward
  entirely through community series-proposal submissions (see Data Model) —
  it is not an auto-synced/rebuildable table the way AniDex's AniList-sourced
  tables are.
- **Per-episode data**: hand-compiled, cited research per show — reading
  public sources (wiki prose, forum discussions, official chronology guides)
  and cross-referencing multiple sources rather than trusting one, the same
  way a human editor building this by hand would. Not an automated scrape of
  any single site's database.
- **Ruled out, with reasons** (don't re-litigate these without new
  information): **animefillerlist.tv** (no API; ToS explicitly forbids
  scraping/republishing — confirmed 2026-08-22 this is a *separate* site
  from animefillerlist.com, not the same operator on two domains: `.tv`
  was registered 2026-04-12 and has been live with real content only since
  ~June 2026, vs. `.com`'s 2013 registration and Drupal 7 stack. No shared
  branding, cross-linking, or platform between them found. **animefillerlist.com**
  itself — the long-established, Google-ranked site this project's research
  actually meant — has no ToS/terms page found anywhere on the domain (only
  a 2014-era privacy policy with no scraping/reuse language at all); it was
  never actually cleared for use, just never separately evaluated once `.tv`'s
  hard "no" was mistakenly treated as covering both. **Evaluated separately
  in issue #48 (2026-08-22) and deliberately not pursued as a source
  either** — not because of a ToS (it has none found), but because giving
  full credit for a public API layer over its data still wouldn't be a
  substitute for the actual permission that content's copyright requires,
  and building toward it would undercut this project's own reason for
  existing (cited, cross-referenced, community-editable data, not a wrapper
  around one upstream's compiled work). Treated as an extra cross-reference
  signal during hand-compiled research at most, same spirit as
  manami-project's tags, never as a thing to copy from directly); Simkl's
  catalog API (restricted to Simkl-integrating apps per
  their own published rules, without explicit permission); Jikan/unofficial
  MAL API (has real filler/recap fields, but MAL's own terms prohibit using
  it to populate a separate database); TheTVDB (paywalled since 2020, and its
  filler data — if any — traces back to Anime Filler List anyway, not TVDB's
  own); TMDB (no filler/canon field exists at all); Wikipedia's
  Wikidata/episode-list articles (checked directly for several confirmed
  "has fillers" shows — no per-episode filler/canon signal exists there
  either, contrary to what might be assumed).
