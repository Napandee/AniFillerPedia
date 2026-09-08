# CLAUDE.md Progressive Disclosure — AniFillerPedia

**Date:** 2026-09-08
**Status:** Approved for implementation
**Precedent:** `homelab-scripts` pilot — see that repo's
`docs/superpowers/specs/2026-09-08-claude-md-progressive-disclosure-design.md`
for the tier model and the `@import` finding, which are not restated here.

---

## 1. What is different about this repo

The homelab-scripts pilot established the convention. Two constraints here make a
straight application of it unsafe.

### 1.1 This repository is PUBLIC

`Napandee/AniFillerPedia` is public (`gh repo view` → `"visibility":"PUBLIC"`).
`CLAUDE.local.md` is gitignored (`.gitignore:28`), so its 130,399 characters are
currently private **by construction**.

Moving that content into `docs/` — the pilot's destination — would publish all of
it. Sections explicitly marked private:

| Section | Chars |
|---|---:|
| External-account setup checklist *(private, 2026-08-21)* | 4,958 |
| Outstanding: commercial-licensing contact channel *(private)* | 743 |
| GitHub repo secrets (Settings → Actions → Secrets) | 560 |
| Secrets location | 214 |

Plus 15,284 characters of live-droplet, deploy-pipeline and self-hosted-runner
detail that is appropriate privately and questionable publicly.

A scan for literal credential values (`ghp_`, `github_pat_`, `AKIA`, PEM headers,
Telegram bot tokens) found **none** — the content is pointers and procedure, not
secrets. The exposure is still real and this design must prevent it.

**Therefore this repo needs a private tier that homelab-scripts did not.**

### 1.2 Deletions from CLAUDE.local.md are unrecoverable

Because the file is gitignored, there is no git history to recover from. The
pilot's safety net — "it's in the previous commit" — does not exist here.

**Mitigation:** a verbatim copy of `CLAUDE.local.md` is taken to
`.claude/context/_backup-CLAUDE.local.md.20260908` before any edit. This is a
one-time safety measure, not part of the target structure.

### 1.3 The content is history, not reference

homelab-scripts was reference tables. Here the dominant content is narrative
about work that is already finished.

`CLAUDE.local.md` — 130,399 chars:

| Category | Chars | Share |
|---|---:|---:|
| Shipped-work journal (13 sections, e.g. `#114/#116` at 20,591) | 56,855 | 44% |
| Private / credential | 6,475 | 5% |
| Everything else | 67,040 | 51% |

`CLAUDE.md` — 32,398 chars, of which `Decisions Made` is 19,446 (60%).

---

## 2. Three destinations

The pilot had one destination. This design has three.

| Tier | Location | Tracked | Holds |
|---|---|---|---|
| Public reference | `docs/*.md` | yes — **public** | Architecture, data model, data sources, decision records |
| Private context | `.claude/context/*.md` | **no — gitignored** | Live instance, deploy, runner, accounts, history, lessons |
| Inline guard | `CLAUDE.md` / `CLAUDE.local.md` | mixed | Only what causes a wrong action if unread |

`.claude/context/` is added to `.gitignore` with a comment stating that the repo
is public and the directory must not be un-ignored.

**Routing rule:** content goes to `docs/` only if it would be appropriate to show
a stranger reading the public repo. Anything naming the live host, an external
account, a credential location, or an internal process goes to
`.claude/context/`. When in doubt, private — the cost of a wrong "private" call
is a slightly less useful public doc; the cost of a wrong "public" call is
publication that cannot be undone.

---

## 3. Target structure

```
anifillerpedia/
├── CLAUDE.md                    ← ~5,000 chars, tracked/public
├── CLAUDE.local.md              ← ~3,000 chars, gitignored
├── docs/                        ← TRACKED = PUBLIC
│   ├── API.md                   (existing, unchanged)
│   ├── architecture.md
│   ├── data-model.md
│   ├── data-sources.md
│   └── decisions.md
└── .claude/context/             ← GITIGNORED = PRIVATE
    ├── live-instance.md
    ├── deploy.md
    ├── accounts.md
    ├── lessons.md
    └── history.md
```

### 3.1 CLAUDE.md disposition (32,398 → ~5,000)

| Section | Chars | Disposition |
|---|---:|---|
| Purpose | 1,112 | trim to ~400, **stays** |
| Scope | 1,460 | trim to ~300, **stays** — "what this is not" is a guard |
| Data Source | 3,602 | → `docs/data-sources.md` |
| Data Model | 1,016 | → `docs/data-model.md` |
| Architecture | 1,882 | → `docs/architecture.md` |
| Deploy | 601 | 2-line summary **stays**; detail → `.claude/context/deploy.md` |
| Guardrails — Non-Negotiable | 3,220 | **stays inline, verbatim** — this is the tier-1 set |
| Decisions Made | 19,446 | → `docs/decisions.md` (15 ADRs) |

`Guardrails` is not trimmed. Every entry is a wrong-action rule: track issues
before starting work, merge with `--merge` not squash, never commit secrets,
never scrape a site whose ToS forbids it. The size target for this repo is
therefore ~5,000 rather than the pilot's 4,500 — the guard block alone is 3,220
and shrinking it would defeat the purpose.

### 3.2 CLAUDE.local.md disposition (130,399 → ~3,000)

| Section(s) | Chars | Disposition |
|---|---:|---|
| Header, Repo, Skills | 1,659 | **stays** |
| Recurring lesson: never put files on the droplet outside git | 1,140 | 2-line guard **stays**; full text → `.claude/context/lessons.md` |
| Live instance | 9,860 | → `.claude/context/live-instance.md` |
| Deploy pipeline + Self-hosted runner + repo variables + repo secrets | 6,053 | → `.claude/context/deploy.md` |
| External-account checklist + commercial-licensing + Secrets location | 5,915 | → `.claude/context/accounts.md` |
| Process lessons: parallel-agent batches | 6,604 | → `.claude/context/lessons.md` |
| Origin & research trail | 10,191 | → `.claude/context/history.md` |
| Shipped-work journal (13 sections) | 56,855 | → `.claude/context/history.md`, plus a one-line-per-feature index with issue/PR numbers |
| Visual direction — DECIDED: Playful Fandom | 2,001 | → `docs/decisions.md` (public-safe design decision) |
| State of the project — take-stock (2026-08-21) | 15,757 | **dropped**, replaced by a pointer |
| Roadmap board — GitHub Projects | 14,335 | **dropped**, replaced by a pointer |

### 3.3 The two dropped sections

Both duplicate live state and were 18 days stale at the time of this change:

- **Take-stock (2026-08-21)** — a status snapshot superseded by roughly ten
  shipped features. A stale status snapshot is worse than none, because it reads
  as current.
- **Roadmap board mirror** — a static copy of a live GitHub Projects board.
  Mirroring live data guarantees drift; the board is the source, and the
  `roadmap-audit` skill already reads it.

Replaced by:

```markdown
- Roadmap and current status: read the GitHub Projects board directly, or run
  the `roadmap-audit` skill. Do not mirror it here — a copy goes stale.
```

These are dropped rather than archived, per an explicit decision. They remain in
`.claude/context/_backup-CLAUDE.local.md.20260908` if ever needed.

---

## 4. Verification

`docs/superpowers/verify-context-split.py`, adapted from the pilot. Checks:

1. **privacy** — no content from a private-marked section appears in any tracked
   file, and `.claude/context/` is gitignored. **This check runs first and is
   the one that must never be waived.**
2. **coverage** — every substantive fact in the baseline `CLAUDE.md` and
   `CLAUDE.local.md` is reachable, excluding the two deliberately dropped
   sections.
3. **size** — `CLAUDE.md` ≤ 5,000 chars; `CLAUDE.local.md` ≤ 3,500 chars.
4. **pointers** — every `docs/*.md` and `.claude/context/*.md` has a pointer
   stating its read condition.
5. **no `@import`.**

Check 1 is implemented as: for each private-marked section, take its distinctive
phrases and assert none appears in `git ls-files`-tracked content.

---

## 5. Non-goals

- Not changing application code, schema, or deployment.
- Not editing `docs/API.md` or the existing `docs/superpowers/` specs and plans.
- Not introducing `@import`.
- Not rewriting the Guardrails block.
- Not touching Trellium — the user has work in flight there.

---

## 6. Execution

Branch `claude-md-progressive-disclosure` off `master`, merged via pull request.
Commit messages follow this repo's convention — sentence case, no
conventional-commit prefix — not the homelab-scripts convention.
