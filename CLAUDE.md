# AniFillerPedia — Project Context for Claude Code

## Purpose

An open, community-editable database of anime filler/canon episode data — which
episodes are anime-original ("filler") versus adapted from the source manga
("canon"), with mixed episodes flagged separately. It exists because no
existing option is both genuinely open (freely reusable, no ToS wall) and
API-accessible (see Guardrails — the two closest existing sources each fail
one of those). Standalone project, not part of AniDex — see Decisions Made for
why.

## Scope

**In scope:**
- Per-episode filler/canon/mixed status for anime series, not just a
  series-level "this show has filler" flag.
- A public, unauthenticated read API — no account, no sync requirement, no
  rate-limit wall for reasonable use.
- A community correction workflow (submit/adjust/correct entries) gated by an
  approval flow — not open unmoderated write access.
- A source citation per entry, so every filler/canon claim is traceable to
  where it came from.

**Out of scope — do not build these:**
- Scraping any site whose terms of service forbid it (see Guardrails — this
  ruled out the most complete existing filler-list site).
- Pulling from Simkl's catalog/discovery API without their explicit prior
  permission — their own published rules restrict catalog use to apps that
  also integrate Simkl login/sync, which this project does not (see
  Guardrails).
- Being a personal watch tracker (status, progress, ratings, personal notes)
  — that's a different product; AniDex already does this for its own users
  and is explicitly not the thing this project extends or depends on.
- Monetization/paywall — the owner's explicit intent is a freely-usable
  public resource.

## Data Source

No single upstream system of record (unlike AniDex, which treats AniList as
its system of record). This project's data is bootstrapped from multiple
legitimate sources, deliberately not from one restricted site:

- **Series-level targeting signal**: the `"has fillers"` / `"canon filler"`
  tags in [manami-project/anime-offline-database](https://github.com/manami-project/anime-offline-database)
  (ODbL-licensed, genuinely open) — used to identify *which* shows are worth
  researching in detail, not as a source of per-episode data (it has none).
- **Per-episode data**: hand-compiled, cited research per show — reading
  public sources (wiki prose, forum discussions, official chronology guides)
  and cross-referencing multiple sources rather than trusting one, the same
  way a human editor building this by hand would. Not an automated scrape of
  any single site's database.
- **Ruled out, with reasons** (don't re-litigate these without new
  information): animefillerlist.com (no API, ToS explicitly forbids
  scraping); Simkl's catalog API (restricted to Simkl-integrating apps per
  their own published rules, without explicit permission); Jikan/unofficial
  MAL API (has real filler/recap fields, but MAL's own terms prohibit using
  it to populate a separate database); TheTVDB (paywalled since 2020, and its
  filler data — if any — traces back to Anime Filler List anyway, not TVDB's
  own); TMDB (no filler/canon field exists at all); Wikipedia's
  Wikidata/episode-list articles (checked directly for several confirmed
  "has fillers" shows — no per-episode filler/canon signal exists there
  either, contrary to what might be assumed).

## Data Model

Not yet built. Known requirements, to get right from the start:

- Separate the community-contributed/correctable layer (episode filler/canon
  status, source citations) from anything auto-imported (the series-level
  targeting tag from manami-project) — same spirit as AniDex's own
  AniList-sourced vs. personal-layer table separation, adapted to this
  project's actual data.
- Every entry needs a status (pending/approved) and a citation — no entry
  should be live/authoritative without both a source and at least one
  approval, given the "Wikipedia-style, not open-write" model this project is
  built around.
- An audit trail of who submitted/approved/corrected what — needed for the
  approval-flow model to actually mean something.

## Architecture

Not yet built. No components exist yet — this section gets filled in as real
decisions are made, not speculatively ahead of them.

## Deploy

Not yet decided.

## Guardrails — Non-Negotiable

- Track bugs, enhancements, and research spikes as GitHub issues (use
  `.github/ISSUE_TEMPLATE/task.md`) before starting work on them, not just in
  commit messages or chat — the reasoning needs to be findable later without
  digging through history. When work starts: assign the issue to the repo
  owner (`gh issue edit <n> --add-assignee Napandee`) and reference it in the
  eventual commit(s) with a closing keyword (`Fixes #n` / `Closes #n`) so it
  auto-closes on merge.
- Merge multi-commit feature branches with a real merge commit
  (`gh pr merge --merge`), not squash — pass the flag explicitly.
- Never commit secrets, tokens, or API keys. Env vars only — never hardcoded,
  never logged.
- **Never scrape a site whose terms of service forbid it, and never use a
  throwaway/anonymous account specifically to make a ToS-restricted action
  harder to trace back.** If a data source's terms require asking first
  (e.g. Simkl's), that means actually asking — via a real, attributable
  request — not finding a way around needing to ask. This is the whole
  reason this project's initial data comes from hand-compiled, cited research
  rather than any single scraped or API-restricted source.
- Community-submitted corrections require an approval flow before becoming
  live/authoritative — never wire up direct unmoderated public writes to the
  dataset, even for a "small trusted community" framing. This is a
  structural guarantee, not a policy to remember to enforce manually.
- Ask before any schema migration that could drop or alter existing
  columns/data — additive migrations (new nullable column, new table) are
  fine to just do.
- Ask before changing the deploy pipeline once one exists — changes there
  affect the live deployment path.

## Decisions Made

- **License**: split — [ODbL v1.0](DATA_LICENSE) for the dataset itself,
  [MIT](LICENSE) for code. Matches the precedent set by
  manami-project/anime-offline-database (one of this project's own seed
  sources), which uses the same split. Chosen over a single GPL-3.0 (the
  project-template default) because GPL is a code-copyleft license and
  doesn't map cleanly onto "is this dataset free to reuse" the way a
  data-specific license does; chosen over CC0 because ODbL's attribution +
  share-alike terms keep contributions flowing back to the community rather
  than allowing a downstream paywalled fork with zero obligation back.
- **Standalone from AniDex, not a feature of it**: this started as a spike
  inside AniDex (issue #161, "filler episode tracking") but was deliberately
  split into its own project rather than built as an AniDex feature — the
  owner's explicit intent is a freely-usable public resource other trackers
  could also consume, not something scoped to one personal instance's users.
  AniDex may become a *consumer* of this project's API later, but that's a
  separate future decision, not assumed here.
- **Tech stack**: not yet decided.
