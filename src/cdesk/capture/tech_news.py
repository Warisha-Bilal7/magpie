"""Tech news scraper and Substack idea suggester.

Fetches trending tech stories (Hacker News, tech feeds) and cross-references them
with your actual project captures and chats to generate high-resonance Substack
post pitches grounded in your own work.
"""

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
import sqlite3
from typing import Sequence


STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with", "by",
    "from", "about", "of", "how", "what", "why", "when", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those", "my", "your", "our",
    "its", "as", "if", "not", "no", "new", "more", "can", "will", "show", "ask", "hn",
}


def parse_hnrss_feed(xml_content: str | bytes) -> list[dict]:
    """Parse RSS XML from Hacker News or tech RSS feeds into structured items."""
    if isinstance(xml_content, str):
        xml_bytes = xml_content.encode("utf-8")
    else:
        xml_bytes = xml_content

    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for el in channel.findall("item"):
        title_el = el.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""

        link_el = el.find("link")
        url = (link_el.text or "").strip() if link_el is not None else ""

        pubdate_el = el.find("pubDate")
        published_at = (pubdate_el.text or "").strip() if pubdate_el is not None else None

        desc_el = el.find("description")
        desc_raw = (desc_el.text or "").strip() if desc_el is not None else ""
        desc = re.sub(r"<[^>]+>", " ", desc_raw)
        desc = html.unescape(desc).strip()

        if title:
            items.append({
                "title": title,
                "url": url,
                "description": desc,
                "published_at": published_at,
            })

    return items


def fetch_tech_news(feed_url: str = "https://hnrss.org/frontpage?points=100", timeout: int = 15) -> list[dict]:
    """Fetch live trending stories from Hacker News."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ContentDesk/1.0",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    req = urllib.request.Request(feed_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_bytes = resp.read()
    return parse_hnrss_feed(xml_bytes)


def extract_keywords(text: str) -> list[str]:
    """Extract significant keywords from a headline or summary for FTS searching."""
    words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", text.lower())
    seen = set()
    keywords = []
    for w in words:
        if w not in STOPWORDS and not w.isdigit() and w not in seen:
            seen.add(w)
            keywords.append(w)
    return keywords


def match_trends_with_captures(
    conn: sqlite3.Connection,
    trends: Sequence[dict],
    limit: int = 5,
) -> list[dict]:
    """Match trending external tech news against internal captures in the database."""
    suggestions = []

    for trend in trends:
        headline = trend.get("title", "")
        keywords = extract_keywords(f"{headline} {trend.get('description', '')}")
        if not keywords:
            continue

        # Try searching capture_fts for any matching keyword
        matched_caps = []
        for kw in keywords[:4]:
            try:
                # Safe token query in FTS5
                query_term = f'"{kw}"'
                rows = conn.execute(
                    "SELECT c.id, c.title, c.happened_at, c.body "
                    "FROM capture c "
                    "JOIN capture_fts f ON f.rowid = c.id "
                    "WHERE capture_fts MATCH ? LIMIT 3",
                    (query_term,),
                ).fetchall()
                for r in rows:
                    if r["id"] not in [m["id"] for m in matched_caps]:
                        matched_caps.append(dict(r))
            except sqlite3.OperationalError:
                continue

        if matched_caps:
            # Formulate a sharp post proposal
            post_title = f"Why {headline.split(':')[0]} Hits Differently in Production"
            pitch = (
                f"Connect the trending discussion on '{headline}' to your actual building experience: "
                f"referenced in captures: {', '.join(str(m['title']) for m in matched_caps[:2])}."
            )
            suggestions.append({
                "title": post_title,
                "trend_title": headline,
                "trend_url": trend.get("url"),
                "matched_captures": matched_caps[:3],
                "pitch": pitch,
            })
            if len(suggestions) >= limit:
                break

    return suggestions
