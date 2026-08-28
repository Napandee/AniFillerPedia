"""Conditional-request (ETag / Last-Modified) support for #155 — a cheap
first step before any heavier webhook/changefeed system (see CLAUDE.md
Architecture): a third-party consumer (e.g. a future AniDex integration)
can poll GET /series/{id} and GET /series/{id}/episodes cheaply with
If-None-Match / If-Modified-Since instead of re-fetching the full payload
on every poll.

Deliberately NOT a generic ETag middleware for the whole API — scoped to
just those two named endpoints per #155's own explicit scope. Kept here
(not in a router/service) since both endpoints need the identical
check-request / set-response-headers logic.
"""

from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime

from fastapi import Request, Response


def last_modified_header(dt: datetime) -> str:
    """RFC 7231 IMF-fixdate — the required wire format for both the
    Last-Modified response header and the If-Modified-Since request
    header. Postgres TIMESTAMPTZ columns already round-trip as aware
    datetimes; format_datetime handles the aware -> GMT conversion.
    """
    return format_datetime(dt, usegmt=True)


def etag_for(dt: datetime, *parts: object) -> str:
    """A quoted strong ETag derived from a last-modified timestamp (+ any
    extra identifying parts, e.g. the series id) rather than a hash of the
    full response body — simpler to compute correctly for these two
    endpoints, and just as precise: every caller of this function derives
    `dt` from a column that already changes on every real content change
    the corresponding endpoint exposes (see each call site's own comment
    for exactly which columns feed it).

    Uses full microsecond precision (`dt.isoformat()`), deliberately NOT
    truncated to the second the way the Last-Modified wire format below
    is — Postgres TIMESTAMPTZ has microsecond precision, and two real,
    distinct updates (e.g. two contributions approved back to back in a
    fast-moving moderation queue, or simply a fast automated test) can
    easily land in the same wall-clock second. Truncating the ETag to that
    same second would make it silently fail to change for a real update
    that happened to share a second with the previous one.
    """
    key = "-".join([str(p) for p in parts] + [dt.isoformat()])
    return f'"{key}"'


def not_modified(request: Request, *, etag: str, last_modified: datetime) -> bool:
    """True if the request's own conditional headers already match the
    current state — the caller should then return a bare 304 instead of
    building the full response body/model.

    Checks If-None-Match first (an exact, stronger signal per RFC 7232
    §3.3 — a client sending both is expected to have the server prefer
    ETag) and only falls back to If-Modified-Since when no If-None-Match
    header is present at all.
    """
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        candidates = {tag.strip() for tag in if_none_match.split(",")}
        return etag in candidates or "*" in candidates

    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        try:
            since = parsedate_to_datetime(if_modified_since)
        except (TypeError, ValueError):
            return False
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        # HTTP-date has only whole-second resolution, so compare truncated
        # to the second — otherwise a last_modified with sub-second
        # precision that was never actually on the wire in either
        # direction could spuriously compare as "still modified."
        return int(last_modified.timestamp()) <= int(since.timestamp())

    return False


def apply_conditional_headers(response: Response, *, etag: str, last_modified: datetime) -> None:
    response.headers["ETag"] = etag
    response.headers["Last-Modified"] = last_modified_header(last_modified)
