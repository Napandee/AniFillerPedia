#!/usr/bin/env python3
"""
wiki_scrape_v3.py — canonical Wikipedia episode-list title/air-date extractor.

Supersedes wiki_scrape_v2.py (deleted, never committed — see CLAUDE.local.md
"Update 2026-08-27" for the full bug history). v2 fixed the row-boundary
"swallow forward" bug (bounding each episode's search between consecutive
id="epN" anchors) but had two remaining, undiscovered bugs in its
*within-cell* title parsing:

  1. Compound merged-episode titles ("Title A" / "Title B" in one row, for
     an English dub that combines two Japanese episodes) were truncated to
     only the first quoted segment.
  2. A title containing its own embedded quoted word (e.g. `The 3 "K"s of
     Osaka Case (Part 1)`) was truncated at the inner quote mark.

This version fixes both by using the real HTML structure of a Wikipedia
episode-list "summary" cell instead of naive quote-to-quote regex matching:

  - Every id="epN" anchor bounds one episode's chunk (first occurrence wins
    if a page has duplicate anchors, e.g. a trailing OVA/specials table
    that reuses low episode numbers) — unchanged from v2, still correct.
  - Within one episode's <td class="summary">...</td> cell, only the
    portion BEFORE the "Transliteration:" line (or a Japanese/Chinese/
    Korean-language wikilink, whichever comes first) is title content —
    everything after that is romanization/native-script, never wanted.
  - Within that zone, a cell can contain 0, 1, or more <b>...</b> spans.
    On these pages, a <b> span wraps a *literal translation of the native
    title* (used when no official English dub title exists), while
    non-bold quoted text is the *official* English dub title. If any
    non-bold ("official") segments exist, those are what we want, joined
    with " / " for a merged episode. If the ONLY quoted content is inside
    a <b> span (no official dub title was ever given), that bold segment
    is used instead — this is exactly Meitantei Conan's case.
  - Quote-pair matching within a zone (`_segment_quotes`) is
    boundary-based (rewritten 2026-08-27, see below), not the original
    per-quote lookahead heuristic: scan every `"` in the zone, and split
    into a new segment only where the gap between two consecutive
    quotes is whitespace-only, or a ` / `-style merge separator. Every
    other quote — no matter what precedes/follows it (a letter, another
    quote, punctuation like `!`) — is literal content of whichever
    segment it falls inside, because real Wikipedia markup never leaves
    stray un-quoted title text floating between two genuinely separate
    quoted segments. This is what lets a `<br/>`-separated official title
    and bold literal-translation split into two real segments (One Piece
    episode 36) while a nested quote anywhere inside one title (Meitantei
    Conan's `"K"`, Bleach's `"June Truth"`/`"Pride"`) stays literal
    content of that one segment, with no special-casing needed per
    punctuation shape.

**Update 2026-08-27, found sweeping the live catalog for drift**: the
original per-quote lookahead approach (a `"` is literal only if the very
next character is alnum, or — added later — another `"`) kept needing a
new special case every time a new punctuation shape turned up around an
embedded quoted word/phrase — first `The 3 "K"s...` (quote touching a
letter), then Bleach TYBW episode 378's `"Everything But the Rain "June
Truth""` (quote touching another quote), then Bleach episode 348's
`"Power of the Substitute Badge, Ichigo's "Pride"!"` (quote touching
`!`) — each one silently truncating the title and dropping the real
outer closing quote. Rather than add a fourth special case for whatever
punctuation turns up next, `_segment_quotes` was rewritten around the
gap-based rule described above. Confirmed all three Bleach titles
against the page's own footnotes before fixing, and added them as
reference cases below (episode 348 alongside 377/378, since it needed
its own distinct punctuation shape to catch).

**A fourth, unrelated bug was also found and fixed in the same sweep**:
`_normalize_with_bold` replaced every non-`<b>`/non-`<br>` inline tag
(`<a>`, `<i>`, `<span>`, ...) with a space unconditionally, so a title
with inline markup around bracketed text got spurious inserted spaces
(Toriko episode 108's `[sic?]`, wrapping "sic" in `<i><a>`, rendered as
`[ sic ? ]`). Fixed by only inserting a space for a real `<br>`/`<br/>`
line break; every other tag is consumed with no inserted character,
since a genuine word-break in real Wikipedia HTML already exists as a
literal space character in the surrounding text.

Validated against the five real-world reference cases from
CLAUDE.local.md before being trusted on anything else — see `python3
wiki_scrape_v3.py --selftest`, which fetches the exact live Wikipedia
pages and confirms this extractor independently reproduces the
already-corrected production values for One Piece episodes 11, 40, 42,
49, 80; Meitantei Conan episodes 238, 239; Bleach episodes 348, 377,
378; and Toriko episode 108.
"""

import html
import re
import sys
import urllib.request

USER_AGENT = "AniFillerPedia-data-audit/1.0 (+https://anifillerpedia.wiki; contact via repo issues)"

EP_ID_RE = re.compile(r'id="ep(\d+)"')
TAG_RE = re.compile(r"<[^>]+>")
BOLD_OPEN_RE = re.compile(r"<b\b[^>]*>", re.IGNORECASE)
BOLD_CLOSE_RE = re.compile(r"</b\s*>", re.IGNORECASE)
BR_RE = re.compile(r"<br\s*/?\s*>", re.IGNORECASE)
BDAY_RE = re.compile(r'class="[^"]*\bbday\b[^"]*">(\d{4}-\d{2}-\d{2})<')

CUTOFF_PATTERNS = [
    re.compile(r"transliteration\s*:", re.IGNORECASE),
    re.compile(r'<a[^>]*title="[A-Za-z]+ language"', re.IGNORECASE),
]


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def split_into_episode_chunks(page_html: str) -> dict:
    """Bound every episode strictly between consecutive id="epN" anchors.
    First occurrence of a given N wins (duplicate anchors from a trailing
    OVA/specials table are ignored) — never let a search span forward
    into a neighboring episode's row.
    """
    matches = list(EP_ID_RE.finditer(page_html))
    chunks = {}
    for idx, m in enumerate(matches):
        ep_num = int(m.group(1))
        if ep_num in chunks:
            continue
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(page_html)
        chunks[ep_num] = page_html[start:end]
    return chunks


def _extract_summary_cell(chunk_html: str):
    m = re.search(r'<td\s+class="summary"[^>]*>', chunk_html)
    if not m:
        return None
    start = m.end()
    end = chunk_html.find("</td>", start)
    if end == -1:
        return None
    return chunk_html[start:end]


def _cutoff_zone(cell_html: str) -> str:
    cutoff_idx = len(cell_html)
    for pat in CUTOFF_PATTERNS:
        m = pat.search(cell_html)
        if m and m.start() < cutoff_idx:
            cutoff_idx = m.start()
    return cell_html[:cutoff_idx]


def _normalize_with_bold(zone_html: str):
    """Walk the zone, producing (text, bold_flags) where bold_flags[i] is
    True iff text[i] fell inside a <b>...</b> span. <b>/</b> themselves are
    consumed with no inserted character (bold content is inline with its
    surroundings, e.g. the embedded `"K"` case). A <br>/<br/> is a real
    line break and becomes a single space, since real title content never
    has one embedded mid-title, and it's what a genuine segment boundary
    (e.g. an official title vs. a bold literal-translation title on the
    next line) needs to look like whitespace, not zero characters.

    Every OTHER tag (`<a>`, `<i>`, `<span>`, their closing tags, ...) is
    consumed with NO inserted character — found 2026-08-27 sweeping the
    live catalog: Toriko episode 108's title wraps "sic" in
    `<i><a ...>sic</a>?</i>` inside a `[...]`, and inserting a space for
    every one of those inline tag boundaries produced `[ sic ? ]` instead
    of the real `[sic?]`. Real HTML never needs a synthesized space at an
    inline tag boundary — any real word-break already exists as a literal
    space character in the surrounding text, so only <br> needs special
    handling."""
    text_chars = []
    bold_flags = []
    bold = False
    i = 0
    n = len(zone_html)
    while i < n:
        c = zone_html[i]
        if c == "<":
            j = zone_html.find(">", i)
            if j == -1:
                break
            tag = zone_html[i : j + 1]
            if BOLD_OPEN_RE.match(tag):
                bold = True
            elif BOLD_CLOSE_RE.match(tag):
                bold = False
            elif BR_RE.match(tag):
                text_chars.append(" ")
                bold_flags.append(bold)
            # else: any other tag (opening/closing) is consumed with no
            # inserted character.
            i = j + 1
            continue
        text_chars.append(c)
        bold_flags.append(bold)
        i += 1
    return "".join(text_chars), bold_flags


# A real boundary between two independently self-contained quoted segments
# is a gap (the text strictly between one quote and the next) that is
# ONE of:
#   - whitespace only (one or more chars — a bold/non-bold transition
#     like One Piece episode 36's `"official"<br/><b>"translation"</b>`,
#     where <br/> normalizes to a single space);
#   - a ` / `-style merge separator (whitespace, a literal `/`,
#     whitespace) — two independently-quoted dub titles (a merged
#     episode, or — found 2026-08-27 on Dragon Ball Z/Super's page — a
#     literal-JP-translation/official-dub pair for one single episode;
#     see CLAUDE.local.md for why that specific case is flagged, not
#     auto-resolved, rather than silently picking one);
#   - whitespace then a literal `(` — a parenthetical annotation
#     (found 2026-08-27: Fullmetal Alchemist's `"Main Title"
#     ("Literal JP Title")`, and Dragon Ball Z/Super's own trailing
#     `("Alternate dub name")`). The segment this opens is tagged
#     PARENTHETICAL below and excluded from the normal official/bold
#     choice — it's always a secondary annotation on the segment before
#     it, never the real title on its own.
# A gap of length ZERO — two quotes touching with nothing at all between
# them, e.g. Bleach episode 378's `..."June Truth""` — is deliberately
# NOT a boundary: that shape is an embedded phrase's own closing quote
# sitting directly next to the real outer closing quote, not two
# adjacent titles.
SLASH_BOUNDARY_RE = re.compile(r"\A\s*/\s*\Z")
PAREN_BOUNDARY_RE = re.compile(r"\A\s*\(\Z")
SPACE_BOUNDARY_RE = re.compile(r"\A\s+\Z")


def _segment_quotes(text: str, bold_flags: list):
    """Return list of (content, is_bold, is_parenthetical) for each real
    quoted segment.

    Rewritten 2026-08-27 (see CLAUDE.local.md "Update 2026-08-27") from a
    sequential state-machine that classified each `"` one at a time via
    lookahead heuristics (is the next char alnum? another quote?). That
    approach kept failing on new punctuation shapes around an embedded
    quoted word/phrase — first `The 3 "K"s...` (quote touching a letter),
    then Bleach TYBW episode 378's `"Everything But the Rain "June
    Truth""` (quote touching another quote), then Bleach episode 348's
    `"Power of the Substitute Badge, Ichigo's "Pride"!"` (quote touching
    `!`) — tripping the exact same mis-detection bug in a new disguise
    every time a new punctuation shape turned up.

    This version is boundary-based instead of sequential: scan all quote
    positions in the zone, and only split into a new segment where the
    gap between two consecutive quotes matches one of the three boundary
    patterns above (whitespace, a ` / ` merge separator, or a `(`
    parenthetical opener). Every other quote — including one immediately
    touching a letter/digit, another quote, or punctuation like `!` — is
    literal content of whichever segment it falls inside, because real
    Wikipedia markup never leaves stray un-quoted title text floating
    between two genuinely separate quoted segments; a non-trivial gap
    always means the quotes on either side of it are still part of the
    SAME title (e.g. Meitantei Conan's
    `"<b>The 3 "K"s of Osaka Case (Part 1)</b>"` — none of its 3
    inter-quote gaps match any boundary pattern, so it stays one segment
    end to end, nested quotes and all — while One Piece episode 36's
    `"The Belle of the Brawl"<br/><b>"Survive!..."</b>` DOES have a
    whitespace-only gap between its two quote pairs, so it correctly
    splits into two: one non-bold (official, used), one bold (literal
    translation, only used as a fallback when no official segment
    exists)."""
    quote_positions = [i for i, c in enumerate(text) if c == '"']
    if len(quote_positions) < 2:
        return []

    # indices into quote_positions marking a real gap, each paired with
    # whether that gap opens a parenthetical annotation on the segment
    # that follows it.
    boundary_idx = []
    for k in range(len(quote_positions) - 1):
        q1, q2 = quote_positions[k], quote_positions[k + 1]
        between = text[q1 + 1 : q2]
        if PAREN_BOUNDARY_RE.match(between):
            boundary_idx.append((k, True))
        elif SLASH_BOUNDARY_RE.match(between) or SPACE_BOUNDARY_RE.match(between):
            boundary_idx.append((k, False))

    def make_segment(open_pos, close_pos, is_parenthetical):
        content = text[open_pos + 1 : close_pos]
        bold_slice = bold_flags[open_pos + 1 : close_pos]
        is_bold = bool(bold_slice) and (
            sum(1 for b in bold_slice if b) > len(bold_slice) / 2
        )
        return (" ".join(content.split()), is_bold, is_parenthetical)

    segments = []
    start_idx = 0
    next_is_parenthetical = False  # the very first segment never is
    for k, opens_paren in boundary_idx:
        segments.append(
            make_segment(quote_positions[start_idx], quote_positions[k], next_is_parenthetical)
        )
        start_idx = k + 1
        next_is_parenthetical = opens_paren
    if start_idx < len(quote_positions):
        open_pos = quote_positions[start_idx]
        close_pos = quote_positions[-1]
        if close_pos > open_pos:
            segments.append(make_segment(open_pos, close_pos, next_is_parenthetical))
    return segments


def extract_title(chunk_html: str):
    cell = _extract_summary_cell(chunk_html)
    if cell is None:
        return None
    zone = _cutoff_zone(cell)
    text, bold_flags = _normalize_with_bold(zone)
    text = html.unescape(text)
    segments = _segment_quotes(text, bold_flags)
    if not segments:
        return None
    # A parenthetical segment (found 2026-08-27: Fullmetal Alchemist's
    # `"Main Title" ("Literal JP Title")`) is always a secondary
    # annotation on the segment before it, never the real title on its
    # own — excluded from the normal official/bold choice, and only used
    # as an absolute last resort if literally nothing else was found.
    non_paren = [(c, b) for c, b, p in segments if not p]
    official = [content for content, is_bold in non_paren if not is_bold and content]
    bold = [content for content, is_bold in non_paren if is_bold and content]
    parenthetical = [content for content, _, p in segments if p and content]
    chosen = official if official else (bold if bold else parenthetical)
    if not chosen:
        return None
    return " / ".join(chosen)


def extract_date(chunk_html: str):
    m = BDAY_RE.search(chunk_html)
    return m.group(1) if m else None


def extract_all(page_html: str) -> dict:
    """Returns {episode_number: {"title": str|None, "aired_at": str|None}}"""
    out = {}
    for ep_num, chunk in split_into_episode_chunks(page_html).items():
        out[ep_num] = {
            "title": extract_title(chunk),
            "aired_at": extract_date(chunk),
        }
    return out


# ---------------------------------------------------------------------------
# Self-test: fetch the two real reference-case pages and confirm this
# extractor independently reproduces the already-corrected production
# values, before trusting it on anything else.
# ---------------------------------------------------------------------------

REFERENCE_CASES = [
    (
        "https://en.wikipedia.org/wiki/List_of_One_Piece_episodes_(seasons_1%E2%80%938)",
        {
            11: "The Bluff and the Bluffer / The War at the Shore",
            36: "The Belle of the Brawl",
            40: "Arms Against Arms / The Comeback Kid",
            42: "The Comeback Kid / Wanted!",
            49: "Roguetown / Switched Blades",
            62: "Fantastic Voyage",
            79: "Saving Nami",
            80: "Saving Nami / Rabid Rabbits",
        },
    ),
    (
        "https://en.wikipedia.org/wiki/List_of_Case_Closed_episodes_(seasons_1%E2%80%9315)",
        {
            238: 'The 3 "K"s of Osaka Case (Part 1)',
            239: 'The 3 "K"s of Osaka Case (Part 2)',
        },
    ),
    (
        # Found 2026-08-27 sweeping the live catalog for drift (see
        # CLAUDE.local.md): episode 378's title has an embedded quoted
        # phrase ("June Truth") whose own closing quote sits directly
        # against the real outer closing quote, with nothing between —
        # a third, until-then-undiscovered bug in this same file's
        # quote-segmentation logic. Confirmed against the page's own
        # footnote ("Stylized as \"EVERYTHING BUT THE RAIN “June Truth”\"")
        # before fixing. Episode 377 (no embedded phrase) is included as
        # a same-page control to confirm the fix doesn't regress the
        # ordinary case.
        "https://en.wikipedia.org/wiki/List_of_Bleach_episodes",
        {
            377: "Everything But the Rain",
            378: 'Everything But the Rain "June Truth"',
            # Found in the same sweep: episode 348's embedded quoted word
            # ("Pride") is followed by "!" before the real outer closing
            # quote — a different punctuation shape than 378's, which is
            # exactly why the sequential-heuristic approach kept failing
            # (each new shape needed its own special case) and prompted
            # the rewrite to a boundary-based segmenter instead.
            348: 'Power of the Substitute Badge, Ichigo\'s "Pride"!',
        },
    ),
    (
        # Found 2026-08-27, same sweep: a fourth bug, unrelated to quote
        # segmentation — every non-<b>/<br> inline tag (e.g. <i>, <a>) was
        # replaced with a space unconditionally, so a title with inline
        # markup around bracketed text got spurious spaces inserted
        # around it. Episode 108's "[sic?]" (wrapping "sic" in <i><a>)
        # rendered as "[ sic ? ]" before the fix.
        "https://en.wikipedia.org/wiki/List_of_Toriko_episodes",
        {
            108: "Tradgedy! [sic?] The Demise of Shokurin Temple... Farewell Komatsu!",
        },
    ),
]


def run_selftest() -> bool:
    ok = True
    for url, expected in REFERENCE_CASES:
        print(f"Fetching {url}")
        page = fetch_html(url)
        chunks = split_into_episode_chunks(page)
        for ep_num, expected_title in expected.items():
            chunk = chunks.get(ep_num)
            if chunk is None:
                print(f"  ep {ep_num}: MISSING chunk")
                ok = False
                continue
            got = extract_title(chunk)
            status = "OK" if got == expected_title else "MISMATCH"
            if status != "OK":
                ok = False
            print(f"  ep {ep_num}: {status}  got={got!r}  expected={expected_title!r}")
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        success = run_selftest()
        print("\nSELFTEST", "PASSED" if success else "FAILED")
        sys.exit(0 if success else 1)
    else:
        print(__doc__)
        print("Run with --selftest to validate against the reference cases.")
