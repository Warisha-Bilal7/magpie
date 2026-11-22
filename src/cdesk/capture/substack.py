"""Substack feed parser and past-post importer.

Fetches public RSS feeds for Substack publications or handles, converts
HTML articles into clean markdown text, and imports them into the workspace
voice corpus (past_post) with deduplication.
"""

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
import sqlite3
from typing import Callable


def resolve_feed_url(url_or_handle: str) -> str:
    """Normalize a Substack handle, profile URL, or publication domain to its RSS feed URL."""
    s = url_or_handle.strip().rstrip("/")
    if s.endswith("/feed"):
        return s

    # Handle profile URLs: https://substack.com/@handle
    m_profile = re.match(r"^https?://substack\.com/@([a-zA-Z0-9_-]+)", s, re.I)
    if m_profile:
        handle = m_profile.group(1)
        return f"https://{handle}.substack.com/feed"

    # Handle publication domains: https://xyz.substack.com
    m_pub = re.match(r"^https?://([a-zA-Z0-9_-]+)\.substack\.com", s, re.I)
    if m_pub:
        return f"{s}/feed"

    # Handle bare handle (e.g. warishadaninbilal)
    if re.match(r"^[a-zA-Z0-9_-]+$", s):
        return f"https://{s}.substack.com/feed"

    # Default fallback: append /feed if full URL
    if s.startswith("http://") or s.startswith("https://"):
        return f"{s}/feed"

    return f"https://{s}.substack.com/feed"


def clean_html_to_markdown(html_content: str) -> str:
    """Convert Substack article HTML into clean, readable text/markdown."""
    if not html_content:
        return ""

    text = html_content
    # Normalize line breaks
    text = re.sub(r"<(?:br|br\s*/)>", "\n", text, flags=re.I)
    # Headings to markdown
    for level in range(1, 7):
        text = re.sub(rf"<h{level}[^>]*>(.*?)</h{level}>", rf"\n\n{'#' * level} \1\n\n", text, flags=re.I | re.S)
    # Paragraphs to double linebreaks
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\n\n\1\n\n", text, flags=re.I | re.S)
    # Blockquotes
    text = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>", r"\n\n> \1\n\n", text, flags=re.I | re.S)
    # Inline code
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.I | re.S)
    # Links: preserve text
    text = re.sub(r"<a\s+(?:[^>]*?\s+)?href=([\"'])(.*?)\1[^>]*>(.*?)</a>", r"[\3](\2)", text, flags=re.I | re.S)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities (&amp;, &quot;, &#39;, etc.)
    text = html.unescape(text)
    # Clean up whitespace
    lines = [line.strip() for line in text.splitlines()]
    cleaned = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned.append("")
                prev_empty = True
        else:
            cleaned.append(line)
            prev_empty = False

    return "\n".join(cleaned).strip()


def parse_substack_feed(xml_content: str | bytes) -> list[dict]:
    """Parse RSS XML content into a list of post dictionaries: {title, url, published_at, body}."""
    if isinstance(xml_content, str):
        xml_bytes = xml_content.encode("utf-8")
    else:
        xml_bytes = xml_content

    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []

    namespaces = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }

    posts = []
    for item in channel.findall("item"):
        title_el = item.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""

        link_el = item.find("link")
        url = (link_el.text or "").strip() if link_el is not None else ""

        pubdate_el = item.find("pubDate")
        published_at = None
        if pubdate_el is not None and pubdate_el.text:
            try:
                dt = parsedate_to_datetime(pubdate_el.text)
                published_at = dt.strftime("%Y-%m-%d")
            except Exception:
                published_at = pubdate_el.text.strip()

        # Try content:encoded first (full text), then fallback to description
        body_raw = ""
        content_el = item.find("content:encoded", namespaces)
        if content_el is not None and content_el.text:
            body_raw = content_el.text
        else:
            desc_el = item.find("description")
            if desc_el is not None and desc_el.text:
                body_raw = desc_el.text

        body = clean_html_to_markdown(body_raw)
        if not body:
            continue

        posts.append({
            "title": title,
            "url": url,
            "published_at": published_at,
            "body": body,
        })

    return posts


def fetch_substack_feed(url_or_handle: str, timeout: int = 15) -> list[dict]:
    """Fetch and parse a live Substack publication RSS feed."""
    feed_url = resolve_feed_url(url_or_handle)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ContentDesk/1.0",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    req = urllib.request.Request(feed_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_bytes = resp.read()
    return parse_substack_feed(xml_bytes)


def import_substack_posts(
    conn: sqlite3.Connection,
    workspace_id: int,
    url_or_handle: str,
    embedder: Callable[[list[str]], "object"] | None = None,
) -> list[int]:
    """Fetch posts from a Substack feed and insert non-duplicate posts into past_post."""
    from ..workspaces import add_past_post, index_workspace_embeddings

    posts = fetch_substack_feed(url_or_handle)
    existing_urls = {
        row["url"]
        for row in conn.execute(
            "SELECT url FROM past_post WHERE workspace_id = ? AND url IS NOT NULL",
            (workspace_id,),
        ).fetchall()
    }

    added_ids = []
    for post in posts:
        if post["url"] and post["url"] in existing_urls:
            continue
        pid = add_past_post(
            conn,
            workspace_id,
            post["body"],
            url=post["url"],
            published_at=post["published_at"],
        )
        added_ids.append(pid)
        if post["url"]:
            existing_urls.add(post["url"])

    if added_ids:
        try:
            index_workspace_embeddings(conn, workspace_id, embedder=embedder)
        except Exception:
            pass

    return added_ids
