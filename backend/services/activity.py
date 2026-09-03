from xml.sax.saxutils import escape

from sqlalchemy.ext.asyncio import AsyncSession

import repositories.activity as activity_repo
from core.config import get_settings
from schemas.activity import ActivityFeedItem, ActivityFeedOut


async def list_recent_activity(session: AsyncSession, limit: int, offset: int) -> ActivityFeedOut:
    rows, total = await activity_repo.list_recent_activity(session, limit, offset)
    return ActivityFeedOut(
        items=[ActivityFeedItem(**row._mapping) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _item_title(item: ActivityFeedItem) -> str:
    verb = {"approved": "Approved", "rejected": "Rejected", "withdrawn": "Withdrawn"}.get(
        item.review_status, item.review_status
    )
    if item.event_type == "contribution":
        return f"{verb}: {item.series_title} episode {item.episode_number} → {item.proposed_status}"
    return f"{verb}: series proposal — {item.proposal_title}"


def _item_link(item: ActivityFeedItem, base_url: str) -> str:
    if item.event_type == "contribution" and item.series_slug:
        return f"{base_url}/series/{item.series_slug}"
    if item.event_type == "contribution":
        return f"{base_url}/series/{item.series_id}"
    return base_url


def render_rss(feed: ActivityFeedOut) -> str:
    """#154: "and/or RSS feed" — cheap to add given `list_recent_activity`
    above already returns exactly the rows an RSS `<item>` needs, so this
    is a plain string-templated render, not a new dependency (no feedgen/
    similar library — the feed's shape is fixed and small enough that
    pulling one in would be more code than it saves).
    """
    settings = get_settings()
    base_url = settings.public_base_url.rstrip("/")

    items_xml = "\n".join(
        f"""    <item>
      <title>{escape(_item_title(item))}</title>
      <link>{escape(_item_link(item, base_url))}</link>
      <guid isPermaLink="false">{item.event_type}-{item.id}</guid>
      <pubDate>{item.reviewed_at.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <description>{escape(item.review_note or "")}</description>
    </item>"""
        for item in feed.items
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AniFillerPedia — Recent changes</title>
    <link>{escape(base_url)}/activity</link>
    <description>Recently resolved episode-status contributions and series proposals.</description>
{items_xml}
  </channel>
</rss>
"""
