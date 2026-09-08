#!/usr/bin/env python3
"""Verify the AniFillerPedia CLAUDE.md split.

THIS REPO IS PUBLIC. docs/ is published; .claude/context/ is gitignored.
Check `privacy` therefore runs first and is the one that must never be waived.

Checks (spec section 4):
  1. privacy   no phrase from a private-marked section appears in any tracked
               file, and .claude/context/ is gitignored
  2. coverage  every substantive fact in the baseline CLAUDE.md and
               CLAUDE.local.md is still reachable (minus the two sections
               deliberately dropped)
  3. size      CLAUDE.md <= 5000 chars, CLAUDE.local.md <= 3500
  4. pointers  every docs/*.md and .claude/context/*.md has a pointer
  5. imports   no @import directives
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKUP = REPO / ".claude" / "context" / "_backup-CLAUDE.local.md.20260908"
MAX_CLAUDE = 5000
MAX_LOCAL = 3500

# Sections of CLAUDE.local.md whose content must never reach a tracked file.
PRIVATE_SECTIONS = [
    "External-account setup checklist",
    "Outstanding: commercial-licensing",
    "GitHub repo secrets",
    "Secrets location",
    "Live instance",
    "Deploy pipeline",
    "Self-hosted runner",
]

# Sections deliberately dropped (spec 3.3): live state that must not be mirrored.
DROPPED_SECTIONS = [
    "State of the project",
    "Roadmap board",
]

GENERIC = {
    "main", "master", "build", "deploy", ".env", "*.json", "git diff",
    "backend/", "frontend/", "docs/", "canon", "filler", "mixed",
    "curl", "jq", "git", "bash", "python3", "node",
}

SUBSTANTIVE = re.compile(
    r"""^(?:
          /\w[\w.-]*(?:/[\w.*~-]+)+
        | ~/[\w./*~-]+
        | (?:\d{1,3}\.){3}\d{1,3}(?::\d+)?
        | https?://\S+
        | [\w][\w.-]*\.(?:sh|py|yml|yaml|json|md|service|timer|env|template|cfg|sql|ts|tsx|astro)
        | Napandee/[\w.-]+
        )$""",
    re.VERBOSE,
)


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def sections(text):
    """Map H2 title -> body, for a markdown document."""
    out = {}
    for block in text.split("\n## ")[1:]:
        out[block.split("\n")[0].strip()] = block
    return out


def facts(text):
    out = set()
    for tok in re.findall(r"`([^`\n]{3,80})`", text):
        tok = tok.strip()
        if tok and tok not in GENERIC and SUBSTANTIVE.match(tok):
            out.add(tok)
    return out


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return [REPO / line for line in out.splitlines() if line]


def phrases(body, n=3, minlen=40):
    """Distinctive long phrases from a section body, for leak detection."""
    found = []
    # skip line 0: it is the section title. A leaked heading is a weak signal;
    # what matters is whether the section's *content* reached a tracked file.
    for line in body.split("\n")[1:]:
        line = line.strip().lstrip("-*# ").strip()
        line = re.sub(r"[`*_\[\]()]", "", line)
        if len(line) >= minlen and not line.startswith("|"):
            found.append(line[:80])
        if len(found) >= n:
            break
    return found


def main():
    claude = read(REPO / "CLAUDE.md")
    local = read(REPO / "CLAUDE.local.md")
    baseline_local = read(BACKUP)
    baseline_claude = subprocess.run(
        ["git", "-C", str(REPO), "show", "master:CLAUDE.md"],
        capture_output=True, text=True, check=True).stdout

    docs = [p for p in sorted((REPO / "docs").glob("*.md"))]
    ctx = [p for p in sorted((REPO / ".claude" / "context").glob("*.md"))
           if not p.name.startswith("_backup")]

    failures = []

    # ---- 1. privacy (first, always) ----
    base_secs = sections(baseline_local)
    leaks = []
    tracked = tracked_files()
    tracked_text = {p: read(p) for p in tracked if p.suffix in {".md", ".txt", ".py", ".yml", ".yaml"}}
    for name in PRIVATE_SECTIONS:
        body = next((b for t, b in base_secs.items() if t.startswith(name)), None)
        if body is None:
            continue
        for ph in phrases(body):
            for p, text in tracked_text.items():
                if ph and ph in text:
                    leaks.append((name, p.relative_to(REPO).as_posix(), ph[:60]))
    ignored = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", ".claude/context/"],
        capture_output=True, text=True).returncode == 0
    if not ignored:
        leaks.append(("(directory)", ".claude/context/", "NOT GITIGNORED"))
    if leaks:
        failures.append("privacy")
        print(f"FAIL privacy: {len(leaks)} private phrase(s) found in tracked files")
        for name, where, ph in leaks[:12]:
            print(f"       [{name}] -> {where}: {ph}")
    else:
        print(f"PASS privacy: no private content tracked; .claude/context/ is gitignored")

    # ---- 2. coverage ----
    dropped_facts = set()
    for name in DROPPED_SECTIONS:
        body = next((b for t, b in base_secs.items() if t.startswith(name)), "")
        dropped_facts |= facts(body)
    required = (facts(baseline_claude) | facts(baseline_local)) - dropped_facts
    corpus = "\n".join([claude, local] + [read(p) for p in docs] + [read(p) for p in ctx])
    missing = sorted(f for f in required if f not in corpus)
    if missing:
        failures.append("coverage")
        print(f"FAIL coverage: {len(missing)} baseline fact(s) unreachable")
        for f in missing[:15]:
            print(f"       lost: {f}")
    else:
        print(f"PASS coverage: all {len(required)} baseline fact(s) reachable")

    # ---- 3. size ----
    ok = True
    for label, text, limit in (("CLAUDE.md", claude, MAX_CLAUDE),
                               ("CLAUDE.local.md", local, MAX_LOCAL)):
        if len(text) > limit:
            ok = False
            print(f"FAIL size: {label} is {len(text)} chars (limit {limit})")
        else:
            print(f"PASS size: {label} is {len(text)} chars (limit {limit})")
    if not ok:
        failures.append("size")

    # ---- 4. pointers ----
    pointer_text = claude + "\n" + local
    want = [p for p in docs if p.name != "API.md"] + ctx
    unpointed = [p.name for p in want if p.name not in pointer_text]
    if unpointed:
        failures.append("pointers")
        print(f"FAIL pointers: no pointer for {', '.join(unpointed)}")
    else:
        print(f"PASS pointers: all {len(want)} split file(s) pointed to")

    # ---- 5. imports ----
    imports = [p.name for p in [REPO / "CLAUDE.md", REPO / "CLAUDE.local.md"] + docs + ctx
               if any(l.startswith("@") for l in read(p).split("\n"))]
    if imports:
        failures.append("imports")
        print(f"FAIL imports: @import found in {', '.join(imports)}")
    else:
        print("PASS imports: no @import directives")

    if failures:
        print(f"\n{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
