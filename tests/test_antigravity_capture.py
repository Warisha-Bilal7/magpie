"""Tests for Antigravity chat transcript extraction and Tech News suggestion engine."""

import json
import pytest
from cdesk.db import init_db
from cdesk.capture.antigravity_chats import parse_transcript_text, import_antigravity_session
from cdesk.capture.tech_news import (
    parse_hnrss_feed,
    match_trends_with_captures,
)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


SAMPLE_JSONL = """{"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "<USER_REQUEST>I am building a local-first content engine for Substack and LinkedIn</USER_REQUEST>", "created_at": "2026-11-20T10:00:00Z"}
{"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Here is an architecture using deterministic verifiers and SQLite.", "created_at": "2026-11-20T10:01:00Z"}
{"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "<USER_REQUEST>How do we prevent hallucinations when generating resume bullets?</USER_REQUEST>", "created_at": "2026-11-20T10:05:00Z"}
{"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Extract numbers and dates and check against source receipts.", "created_at": "2026-11-20T10:06:00Z"}
"""


def test_parse_transcript_text():
    conv = parse_transcript_text(SAMPLE_JSONL, conv_id="test-conv-123")
    assert conv is not None
    assert "local-first content engine" in conv["body"]
    assert "hallucinations when generating resume bullets" in conv["body"]
    assert conv["origin"] == "antigravity:test-conv-123"
    assert "local-first content engine" in conv["title"].lower() or "building" in conv["title"].lower()
    assert conv["happened_at"] == "2026-11-20"


def test_import_antigravity_session(conn):
    cap_id, created = import_antigravity_session(conn, SAMPLE_JSONL, conv_id="test-conv-123")
    assert cap_id is not None
    assert created is True

    # Duplicate should be detected via content_hash (returns (None, False))
    cap_id2, created2 = import_antigravity_session(conn, SAMPLE_JSONL, conv_id="test-conv-123")
    assert cap_id2 is None
    assert created2 is False


SAMPLE_HN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Hacker News Frontpage</title>
    <link>https://news.ycombinator.com/</link>
    <item>
      <title>LLM Hallucinations in Production: Why Synthetic Benchmarks Lie</title>
      <link>https://example.com/llm-hallucinations</link>
      <pubDate>Fri, 20 Nov 2026 12:00:00 GMT</pubDate>
      <description><![CDATA[Discussion on why synthetic benchmarks fail to capture real world failure modes.]]></description>
    </item>
    <item>
      <title>SQLite as an Application File Format</title>
      <link>https://example.com/sqlite-format</link>
      <pubDate>Fri, 20 Nov 2026 14:00:00 GMT</pubDate>
      <description><![CDATA[Using SQLite for local-first software architecture.]]></description>
    </item>
  </channel>
</rss>
"""


def test_parse_hnrss_feed():
    trends = parse_hnrss_feed(SAMPLE_HN_XML)
    assert len(trends) == 2
    assert "LLM Hallucinations" in trends[0]["title"]
    assert trends[0]["url"] == "https://example.com/llm-hallucinations"
    assert "SQLite" in trends[1]["title"]


def test_match_trends_with_captures(conn):
    # First add a capture in our database
    import_antigravity_session(conn, SAMPLE_JSONL, conv_id="test-conv-123")

    trends = parse_hnrss_feed(SAMPLE_HN_XML)
    suggestions = match_trends_with_captures(conn, trends)

    assert len(suggestions) > 0
    s = suggestions[0]
    assert "title" in s
    assert "trend_title" in s
    assert "matched_captures" in s
    assert len(s["matched_captures"]) > 0
