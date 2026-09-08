# CLAUDE.md Progressive Disclosure — AniFillerPedia Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `CLAUDE.md` 32,398 → ≤5,000 chars and `CLAUDE.local.md` 130,399 → ≤3,500, routing content to a public `docs/` tier and a gitignored `.claude/context/` private tier, publishing nothing that is private today.

**Architecture:** Each task moves one group of sections and re-runs a verifier whose **privacy check runs first**. Public and private destinations are never mixed within a task, so a mistake is contained to one commit.

**Spec:** `docs/superpowers/specs/2026-09-08-claude-md-progressive-disclosure-design.md`

## Global Constraints

- **This repo is PUBLIC.** `docs/` is published. `.claude/context/` is gitignored and must stay so.
- When unsure whether content is public-safe, it goes to `.claude/context/`.
- `Guardrails — Non-Negotiable` in `CLAUDE.md` is **not edited or trimmed**.
- Default branch is `master`. Commit messages are **sentence case, no `feat:`/`docs:` prefix** — this repo's convention, not homelab-scripts'.
- No `@import`.
- Do not edit `docs/API.md` or existing `docs/superpowers/` specs and plans.
- `.claude/context/_backup-CLAUDE.local.md.20260908` is the pre-change safety copy. Never delete it during this work; never track it.

### Baseline section inventory

`CLAUDE.md` (32,398): Purpose 1,112 · Scope 1,460 · Data Source 3,602 · Data Model 1,016 · Architecture 1,882 · Deploy 601 · Guardrails 3,220 · Decisions Made 19,446

`CLAUDE.local.md` (130,399): header/Repo/Skills 1,659 · Origin trail 10,191 · Live instance 9,860 · Deploy pipeline 2,363 · Self-hosted runner 3,061 · repo vars 69 · repo secrets 560 · External accounts 4,958 · Licensing contact 743 · Secrets location 214 · Droplet lesson 1,140 · Parallel-agent lessons 6,604 · Visual direction 2,001 · Take-stock 15,757 · Roadmap mirror 14,335 · 13 shipped sections 56,855

---

### Task 1: Verifier with privacy check

**Files:** Create `docs/superpowers/verify-context-split.py`

**Produces:** `python3 docs/superpowers/verify-context-split.py` → exit 0 when all checks pass. Every later task runs it verbatim.

- [ ] **Step 1: Write the verifier**

Adapt the homelab-scripts verifier. Required differences:

- **Check `privacy` runs FIRST.** For each private-marked section title in the baseline `CLAUDE.local.md` (External-account setup checklist, Outstanding: commercial-licensing, GitHub repo secrets, Secrets location, Live instance, Deploy pipeline, Self-hosted runner), take 3 distinctive ≥40-char phrases and assert none appears in any file listed by `git ls-files`. Also assert `git check-ignore .claude/context/` succeeds.
- **Two size limits:** `CLAUDE.md` ≤ 5,000; `CLAUDE.local.md` ≤ 3,500.
- **Coverage baseline is both files**, from `git show master:CLAUDE.md` and from `.claude/context/_backup-CLAUDE.local.md.20260908` (CLAUDE.local.md is untracked, so git cannot supply its baseline).
- **Coverage excludes** facts appearing only in the take-stock and roadmap-mirror sections, which are deliberately dropped. Build that exclusion set from those two sections of the backup.
- **Corpus** = `CLAUDE.md` + `CLAUDE.local.md` + `docs/*.md` + `.claude/context/*.md`, minus the backup file.
- **Pointers:** every `docs/*.md` (except `API.md` and `superpowers/`) and every `.claude/context/*.md` (except the backup) is named in `CLAUDE.md` or `CLAUDE.local.md`.

- [ ] **Step 2: Run it; expect privacy PASS, sizes FAIL**

```bash
python3 docs/superpowers/verify-context-split.py; echo "exit=$?"
```

Expected: `PASS privacy` (nothing has moved yet, so nothing private is tracked), `FAIL size` on both files, `PASS coverage`.

- [ ] **Step 3: Prove the privacy check actually detects a leak**

A check that has never failed is not known to work.

```bash
grep -o '[^\n]\{60\}' .claude/context/_backup-CLAUDE.local.md.20260908 \
  | grep -i -m1 'droplet' >> docs/data-sources-LEAKTEST.md
python3 docs/superpowers/verify-context-split.py 2>&1 | grep -i privacy
rm docs/data-sources-LEAKTEST.md
```

Expected: the middle command prints `FAIL privacy`. If it prints PASS, the check is not working — fix it before continuing.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/verify-context-split.py
git commit -m "Add verifier for the CLAUDE.md split, with a privacy check

Privacy runs first: no phrase from a private-marked section may appear in
any tracked file, and .claude/context/ must be gitignored. Proven to fail
on a deliberately planted leak before being trusted."
```

---

### Task 2: Public reference out of CLAUDE.md

**Files:** Create `docs/architecture.md`, `docs/data-model.md`, `docs/data-sources.md`; modify `CLAUDE.md`

- [ ] **Step 1:** Move `## Architecture` (1,882) verbatim to `docs/architecture.md`; `## Data Model` (1,016) to `docs/data-model.md`; `## Data Source` (3,602) to `docs/data-sources.md`. Each gets an H1 title and a one-line preamble.
- [ ] **Step 2:** Delete those three sections from `CLAUDE.md`. Add a `## Where the detail lives` section with a read condition per file:

```markdown
- `docs/architecture.md` — before changing how backend, frontend or database fit together.
- `docs/data-model.md` — when touching schema, episode status values, or series records.
- `docs/data-sources.md` — before adding or changing a scraper or import path.
```

- [ ] **Step 3:** `python3 docs/superpowers/verify-context-split.py` → `PASS privacy`, `PASS coverage`. `CLAUDE.md` ~25,900.
- [ ] **Step 4:** Commit — `"Move architecture, data model and data sources to docs/"`

---

### Task 3: Decision records to docs/decisions.md

**Files:** Create `docs/decisions.md`; modify `CLAUDE.md`

- [ ] **Step 1:** Move `## Decisions Made` (19,446) verbatim to `docs/decisions.md` under an H1 and this preamble:

```markdown
Architectural decisions and why they were made. Each entry states the decision,
the date, and the issue it came from. Entries are appended, not rewritten — a
superseded decision is marked superseded rather than deleted.
```

- [ ] **Step 2:** Delete the section from `CLAUDE.md`; add the pointer:

```markdown
- `docs/decisions.md` — before proposing anything that changes licensing, auth,
  the contribution model, or the episode status vocabulary. Fifteen decisions
  with their reasoning; check it before re-litigating one.
```

- [ ] **Step 3:** Verify. `CLAUDE.md` ~6,500.
- [ ] **Step 4:** Commit — `"Move the decision record to docs/decisions.md"`

---

### Task 4: Private operational context

**Files:** Create `.claude/context/live-instance.md`, `.claude/context/deploy.md`, `.claude/context/accounts.md`; modify `CLAUDE.local.md`, `CLAUDE.md`

**This is the task where a mistake publishes something.** Confirm `git status --porcelain` shows no `.claude/context/` entries before committing.

- [ ] **Step 1:** `## Live instance` (9,860) → `.claude/context/live-instance.md`.
- [ ] **Step 2:** `## Deploy pipeline` + `## Self-hosted runner` + `## GitHub repo variables` + `## GitHub repo secrets` (6,053) → `.claude/context/deploy.md`.
- [ ] **Step 3:** `## External-account setup checklist` + `## Outstanding: commercial-licensing` + `## Secrets location` (5,915) → `.claude/context/accounts.md`.
- [ ] **Step 4:** Delete all of the above from `CLAUDE.local.md`. Add pointers there:

```markdown
- `.claude/context/live-instance.md` — when touching the running site or its data.
- `.claude/context/deploy.md` — when the deploy pipeline or runner misbehaves.
- `.claude/context/accounts.md` — when an external account or credential is involved.
```

- [ ] **Step 5:** In `CLAUDE.md`, reduce `## Deploy` (601) to two lines and point at `.claude/context/deploy.md` for detail.
- [ ] **Step 6:** Verify, and separately assert nothing leaked:

```bash
git status --porcelain | grep '\.claude/context' && echo "LEAK -- STOP" || echo "clean"
python3 docs/superpowers/verify-context-split.py
```

- [ ] **Step 7:** Commit `CLAUDE.md` only (the rest is untracked) — `"Point CLAUDE.md deploy section at the private context file"`

---

### Task 5: Lessons

**Files:** Create `.claude/context/lessons.md`; modify `CLAUDE.local.md`

- [ ] **Step 1:** `## Process lessons: parallel-agent batches` (6,604) + `## Recurring lesson: never put files on the droplet outside git` (1,140) → `.claude/context/lessons.md`.
- [ ] **Step 2:** Keep a two-line guard inline in `CLAUDE.local.md` — the droplet rule is a wrong-action rule:

```markdown
**Never put files on the droplet outside git.** Anything not in the repo is lost
on the next deploy and invisible to review. Full reasoning in
`.claude/context/lessons.md`.
```

- [ ] **Step 3:** Add the pointer; verify.
- [ ] **Step 4:** Nothing tracked changed — record with `git commit --allow-empty` only if a tracked file changed; otherwise skip the commit and note it in the final PR body.

---

### Task 6: History archive and compressed index

**Files:** Create `.claude/context/history.md`; modify `CLAUDE.local.md`

- [ ] **Step 1:** Move `## Origin & research trail` (10,191) and all 13 shipped-work sections (56,855) verbatim into `.claude/context/history.md`, in date order, under an H1 explaining it is an archive of completed work.
- [ ] **Step 2:** Replace them in `CLAUDE.local.md` with a one-line-per-feature index, newest first. Format — issue number, one clause, date:

```markdown
### Shipped (full write-ups in `.claude/context/history.md`)

- #224 local email+password auth — 2026-09-04
- #23 canary entries + log-review process — 2026-09-03
- #115 seventh episode-data batch, first with the fixed scraper — 2026-08-26
```

Derive one line per section from its existing heading. Do not invent detail.

- [ ] **Step 3:** Add the pointer:

```markdown
- `.claude/context/history.md` — when you need why a shipped feature was built
  the way it was, and the PR does not say.
```

- [ ] **Step 4:** Verify. `CLAUDE.local.md` ~35,000 at this point.

---

### Task 7: Drop the stale duplicates, finalise CLAUDE.local.md

**Files:** modify `CLAUDE.local.md`

- [ ] **Step 1:** Delete `## State of the project — take-stock (2026-08-21)` (15,757) and `## Roadmap board — GitHub Projects` (14,335). Both duplicate live state and were 18 days stale. They remain in the backup.
- [ ] **Step 2:** Replace with:

```markdown
- Roadmap and current status: read the GitHub Projects board directly, or run
  the `roadmap-audit` skill. Do not mirror it here — a copy goes stale.
```

- [ ] **Step 3:** Move `## Visual direction — DECIDED: Playful Fandom` (2,001) to `docs/decisions.md` — a design decision, public-safe.
- [ ] **Step 4:** Verify. `CLAUDE.local.md` ≤ 3,500 must now pass.
- [ ] **Step 5:** Commit the `docs/decisions.md` change — `"Record the visual direction with the other decisions"`

---

### Task 8: Finalise CLAUDE.md

**Files:** modify `CLAUDE.md`

- [ ] **Step 1:** Trim `## Purpose` to ~400 chars and `## Scope` to ~300, keeping the "what this is not" boundary — that is a guard.
- [ ] **Step 2:** Confirm `## Guardrails — Non-Negotiable` is byte-identical to baseline:

```bash
diff <(git show master:CLAUDE.md | sed -n '/^## Guardrails/,/^## /p') \
     <(sed -n '/^## Guardrails/,/^## /p' CLAUDE.md) && echo "guardrails intact"
```

- [ ] **Step 3:** Verify — `CLAUDE.md` ≤ 5,000 must pass.
- [ ] **Step 4:** Commit — `"Trim CLAUDE.md to guards and pointers"`

---

### Task 9: Read-through and PR

- [ ] **Step 1:** Read both files start to finish. Every remaining sentence must be a wrong-action rule, not a lookup.
- [ ] **Step 2:** `grep -n '^@' CLAUDE.md CLAUDE.local.md docs/*.md .claude/context/*.md` → expect none.
- [ ] **Step 3:** Final privacy audit against the tracked tree:

```bash
python3 docs/superpowers/verify-context-split.py
git ls-files | xargs grep -l -i 'droplet\|setup checklist\|repo secrets' 2>/dev/null || echo "no private markers tracked"
```

- [ ] **Step 4:** Push and open the PR against `master`.

---

## Self-Review

**Spec coverage:** §1.1 public/private → Tasks 1, 4; §1.2 backup → done pre-plan, guarded in Global Constraints; §2 three destinations → Tasks 2–6; §3.1 CLAUDE.md → Tasks 2, 3, 8; §3.2 CLAUDE.local.md → Tasks 4–7; §3.3 dropped sections → Task 7; §4 verification → Task 1 with all five checks; §5 non-goals → Global Constraints.

**Placeholder scan:** none. Section names and character counts are exact, taken from the baseline inventory.

**Consistency:** the verifier command is identical across Tasks 1–9. Check names (`privacy`, `coverage`, `size`, `pointers`) match the spec §4 ordering, with `privacy` first everywhere.

**Known risk:** Task 5 may produce no tracked change, since both source and destination are untracked. That is expected and is called out in the task rather than papered over with an empty commit.
