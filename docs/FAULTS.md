# Faults

Things that went wrong, and the guard each one produced. Newest first.

Add an entry when something failed in a way that **could recur** and would cost
time or damage if it did. Not typos, not one-off environment hiccups.

Format — all four fields, every time:

    ## YYYY-MM-DD — one-line title
    **What:** the observable failure
    **Why:** the actual cause, not the symptom
    **Guard:** what now prevents it (hook, check, doc), or "none — judgement only"
    **Recurred:** yes/no

`Recurred:` is the field that earns its place. A first slip is noise; the same
failure twice is what justifies a hook rather than a note. If a fault happens
again, edit the existing entry's `Recurred:` to yes and add the date — do not
append a second entry.

No credentials, IPs or hostnames here — this file is about process and stays
public-safe. A fault needing private detail records the shape here and points at
the private tier.

---

## 2026-09-09 — five guard versions passed their own tests while wide open

**What:** a git-safety hook shipped five times (17/17, 26/26, 35/35, 47/47,
65/65 green) each time carrying a complete bypass: `git -C` for all rules;
every other global option; every line after the first; `git add -- .` and
force-suppression from a later command; a `#` in an argument and a reachable
sentinel byte.
**Why:** each fix added parsing to close the last gap, and the added parsing
created the next one. Precision on raw command text costs more than it buys.
**Guard:** the guard was narrowed to three regex checks with no tokenizer.
Bulk-add is now an anchored whole-string match only — it catches the recorded
fault and misses chained forms, deliberately.
**Recurred:** yes — five times in one implementation.

## 2026-09-08 — bulk `git add` published private files to a public repo

**What:** `git add -A` staged `.claude/context` (a symlink to the private
claude-context repo) and `.claude/scratch/` into a public repo, twice.
**Why:** the second branch was cut from `master`, which did not carry the
`.gitignore` entries — they existed only on the feature branch. `git add -A`
then swept in whatever was untracked.
**Guard:** `PreToolUse` deny on bulk `git add`, public repos only
(`.claude/hooks/guard-git.sh --public`).
**Recurred:** yes — twice in one session, the second time after the first was
found and fixed. That recurrence is why this is a hook and not a note.

## 2026-09-08 — a gitignore rule silently stopped matching a symlink

**What:** `.gitignore` had `.claude/context/`. Replacing the real directory with
a symlink made the rule stop matching, leaving the link trackable in a public repo.
**Why:** a trailing slash matches a **directory**; git treats a symlink as a file.
**Guard:** write the pattern without a trailing slash (`.claude/context`), and
`guard-git.sh` denies staging that path regardless.
**Recurred:** no — but it was found twice in one session, once in `.gitignore`
and once in a verifier making the same assumption.

## 2026-08-27 — code merged before its migration, twice in one day

**What:** a PR was merged and deployed via the self-hosted runner before its
schema migration had been applied to production, so the live app 500'd on the
missing column/table until fixed by hand. Happened twice the same day — the
second time despite an explicit instruction to sequence migrate-before-merge.
**Why:** the deploy pipeline was merge → auto-deploy (near-instant) → apply
the migration by hand afterward. That order always leaves a live-outage
window whenever the newly-deployed code unconditionally depends on a column
or table the migration hasn't added yet.
**Guard:** apply the migration (and any backfill the code needs) *before*
merging or pushing app code that depends on it. After any merge that touches
a migration file, independently verify the migration actually landed on the
live database — don't trust a "verified live" report at face value.
**Recurred:** yes — twice in one day, the second time despite an explicit
prior instruction not to.

## 2026-08-21 — an untracked file on the deploy host blocked the next `git pull`

**What:** a file copied directly onto the deploy host to test code, outside
the git checkout, later blocked `git pull` with "would be overwritten by
merge" once the same file arrived properly via git. The first time this
happened it went unnoticed — a stale copy got tested instead of the real
merged code.
**Why:** the deploy host's checkout was treated as a convenient place to drop
test files, rather than as pull-only.
**Guard:** the deploy host's git checkout is pull-only. Anything needed there
for a test is built into the image or placed in a genuinely separate scratch
location — never copied into the checkout directly. If `git pull` ever fails
on an untracked-file conflict, diff it against the incoming file before
deleting it — confirm they're identical rather than assuming.
**Recurred:** yes — twice the same day.
