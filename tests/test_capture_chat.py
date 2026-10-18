import json

import pytest

from cdesk.capture.chat_export import add_chat_export, parse_export


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


def test_chatgpt_export_format(tmp_path):
    data = [{
        "title": "Parser debugging",
        "mapping": {
            "a": {"message": {"role": "user", "content": {"parts": ["why is FTS empty?"]}}},
            "b": {"message": {"role": "assistant", "content": {"parts": ["the rowid was off"]}}},
            "c": {"node": True},
        },
    }]
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    parsed = parse_export(p)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Parser debugging"
    assert "user: why is FTS empty?" in parsed[0]["body"]
    assert "assistant: the rowid was off" in parsed[0]["body"]


def test_generic_messages_format(tmp_path):
    data = {"title": "Voice tuning", "messages": [
        {"role": "user", "content": "make it less formal"},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ]}
    p = tmp_path / "chat.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    parsed = parse_export(p)
    assert parsed[0]["title"] == "Voice tuning"
    assert "user: make it less formal" in parsed[0]["body"]
    assert "assistant: done" in parsed[0]["body"]


def test_markdown_transcript(tmp_path):
    p = tmp_path / "transcript.md"
    p.write_text(
        "## Human\nHow do I export this?\n\n## Assistant\nUse the settings menu.\n",
        encoding="utf-8",
    )
    parsed = parse_export(p)
    assert len(parsed) == 1
    assert "human: How do I export this?" in parsed[0]["body"]


def test_unparseable_json_falls_back_to_paste(tmp_path):
    p = tmp_path / "weird.json"
    p.write_text("{not json", encoding="utf-8")
    parsed = parse_export(p)
    assert len(parsed) == 1
    assert "{not json" in parsed[0]["body"]
    assert parsed[0]["title"] == "weird"


def test_add_chat_export_dedupes_and_tags_origin(conn, tmp_path):
    data = {"title": "t", "messages": [{"role": "user", "content": "hello"}]}
    p = tmp_path / "chat.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    first = add_chat_export(conn, p, origin="gemini")
    second = add_chat_export(conn, p, origin="gemini")
    assert first[0][1] is True
    assert second[0][1] is False
    row = conn.execute("SELECT origin, source FROM capture").fetchone()
    assert row["origin"] == "gemini"
    assert row["source"] == "chat_export"
