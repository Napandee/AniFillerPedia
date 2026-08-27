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
  - Quote-pair matching within a segment tracks HTML tag boundaries: a `"`
    immediately followed by a letter/digit (no tag/space in between) is
    treated as a literal, embedded quote mark inside the title (e.g. the
    `"K"` in `The 3 "K"s of Osaka Case`), not a segment delimiter. A `"`
    followed by a real word-boundary (space, end of zone, a stripped tag)
    is a real delimiter. This is what correctly handles bug #2 above
    without regressing bug #1's fix (merged titles still split on the
    real " / " separator between two non-nested, fully-quoted segments).

Validated against the two real-world reference cases from CLAUDE.local.md
before being trusted on anything else — see `python3 wiki_scrape_v3.py
--selftest`, which fetches the exact live Wikipedia pages and confirms
this extractor independently reproduces the already-corrected production
values for One Piece episodes 11, 40, 42, 49, 80 and Meitantei Conan
episodes 238, 239.
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
    True iff text[i] fell inside a <b>...</b> span. Every non-bold tag is
    replaced with a single space (to preserve word boundaries); <b>/</b>
    themselves are consumed with no inserted character (bold content is
    inline with its surroundings, e.g. the embedded `"K"` case)."""
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
            else:
                text_chars.append(" ")
                bold_flags.append(bold)
            i = j + 1
            continue
        text_chars.append(c)
        bold_flags.append(bold)
        i += 1
    return "".join(text_chars), bold_flags


def _segment_quotes(text: str, bold_flags: list):
    """Return list of (content, is_bold) for each real quoted segment.
    A `"` is a real delimiter only when NOT immediately followed by a
    letter/digit while already inside a segment (that pattern means it's
    an embedded/nested quote mark, e.g. the two quotes around K in
    `The 3 "K"s of Osaka Case`, which stay literal content)."""
    segments = []
    state = "outside"
    seg_start = None
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c == '"':
            if state == "outside":
                state = "inside"
                seg_start = i + 1
            else:
                right = text[i + 1] if i + 1 < n else ""
                if right.isalnum():
                    pass  # embedded quote mark, not a real close
                else:
                    content = text[seg_start:i]
                    bold_slice = bold_flags[seg_start:i]
                    is_bold = bool(bold_slice) and (
                        sum(1 for b in bold_slice if b) > len(bold_slice) / 2
                    )
                    segments.append((" ".join(content.split()), is_bold))
                    state = "outside"
        i += 1
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
    official = [content for content, is_bold in segments if not is_bold and content]
    bold = [content for content, is_bold in segments if is_bold and content]
    chosen = official if official else bold
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
