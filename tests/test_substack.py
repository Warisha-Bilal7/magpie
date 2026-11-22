"""Tests for Substack feed parser, importer, and automated style analyzer."""

import pytest
import sqlite3
from cdesk.db import init_db
from cdesk.workspaces import create_workspace, get_workspace, effective_rules
from cdesk.capture.substack import (
    resolve_feed_url,
    clean_html_to_markdown,
    parse_substack_feed,
)
from cdesk.style_analyzer import (
    analyze_writing_style,
    apply_style_to_workspace,
    detect_unwanted_ai_tropes,
)

SAMPLE_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Warisha's Substack</title>
    <link>https://warishadaninbilal.substack.com</link>
    <description>Engineering notes and reflections</description>
    <item>
      <title>What building a real hallucination detector taught me</title>
      <link>https://warishadaninbilal.substack.com/p/what-building-a-real-hallucination</link>
      <pubDate>Thu, 11 Jun 2026 14:27:08 GMT</pubDate>
      <content:encoded><![CDATA[
        <p>Most papers on hallucination detection evaluate against synthetic benchmarks. In production, real failures look nothing like that.</p>
        <p>We spent three weeks instrumenting our prompt chains. Here is what broke first: latency spiked to 4.2 seconds when we added self-consistency checks.</p>
        <h3>The Latency Penalty</h3>
        <p>If you run three parallel generations to verify facts, your token bill triples. That is not viable for a real-time copilot.</p>
      ]]></content:encoded>
    </item>
    <item>
      <title>Life at NIC</title>
      <link>https://warishadaninbilal.substack.com/p/life-at-nic</link>
      <pubDate>Mon, 28 Sep 2026 21:11:29 GMT</pubDate>
      <description>Reflections on the incubation fellowship and late nights.</description>
      <content:encoded><![CDATA[
        <p>The incubator is quietest at 2 AM. That is usually when the toughest bugs get resolved.</p>
        <p>You cannot fake progress when demo day is two weeks away. Everyone is shipping or breaking things.</p>
      ]]></content:encoded>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_resolve_feed_url():
    assert resolve_feed_url("https://substack.com/@warishadaninbilal") == "https://warishadaninbilal.substack.com/feed"
    assert resolve_feed_url("https://warishadaninbilal.substack.com") == "https://warishadaninbilal.substack.com/feed"
    assert resolve_feed_url("https://warishadaninbilal.substack.com/feed") == "https://warishadaninbilal.substack.com/feed"
    assert resolve_feed_url("warishadaninbilal") == "https://warishadaninbilal.substack.com/feed"
    assert resolve_feed_url("https://example.com/custom/feed") == "https://example.com/custom/feed"


def test_clean_html_to_markdown():
    html = "<p>First para.</p><h3>Section Title</h3><p>Second para with <a href='https://example.com'>a link</a> &amp; code <code>foo()</code>.</p>"
    md = clean_html_to_markdown(html)
    assert "First para." in md
    assert "Section Title" in md
    assert "foo()" in md
    assert "<p>" not in md
    assert "&amp;" not in md


def test_parse_substack_feed():
    posts = parse_substack_feed(SAMPLE_FEED_XML)
    assert len(posts) == 2
    p1 = posts[0]
    assert p1["title"] == "What building a real hallucination detector taught me"
    assert p1["url"] == "https://warishadaninbilal.substack.com/p/what-building-a-real-hallucination"
    assert "synthetic benchmarks" in p1["body"]
    assert "4.2 seconds" in p1["body"]
    assert p1["published_at"] is not None

    p2 = posts[1]
    assert p2["title"] == "Life at NIC"
    assert "quietest at 2 AM" in p2["body"]


def test_analyze_writing_style():
    posts = parse_substack_feed(SAMPLE_FEED_XML)
    profile = analyze_writing_style([p["body"] for p in posts])

    assert "avg_sentence_len" in profile
    assert profile["avg_sentence_len"] > 0
    assert "cadence_notes" in profile
    assert "banned_ai_tropes" in profile
    assert "voice_summary" in profile
    # The sample author doesn't use AI fluff words like 'delve' or 'testament'
    assert "delve" in profile["banned_ai_tropes"]


def test_apply_style_to_workspace(conn):
    ws = create_workspace(conn, "Substack", kind="substack")
    posts = parse_substack_feed(SAMPLE_FEED_XML)
    profile = analyze_writing_style([p["body"] for p in posts])

    updated = apply_style_to_workspace(conn, ws["id"], profile)
    rules = effective_rules(updated)

    assert "delve" in rules.get("banned", [])
    assert rules.get("voice_summary") is not None
    assert "tone_notes" in rules
