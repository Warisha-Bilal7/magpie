"""Journal graph tests: fallback, verify/retry, store, weekly. M2 issues #12-#15, #17."""

import json

import pytest

from cdesk.config import MAX_ATTEMPTS
from cdesk.graphs.journal import (
    JournalLines,
    build_journal_graph,
    fallback_digest,
    journal_router,
    select,
    store,
    summarize,
    verify,
)


@pytest.fixture
def captures():
    return [
        {"id": 1, "origin": "opencode", "title": "Deploy", "body": "Shipped v2 on 4 Nov.", "happened_at": "2026-10-14"},
        {"id": 2, "origin": "gemini", "title": "Standup", "body": "Discussed the failing tests.", "happened_at": "2026-10-14"},
    ]


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


# --- fallback digest (#15) --------------------------------------------------

def test_fallback_digest_one_cited_line_per_capture(captures):
    lines = fallback_digest({"captures": captures})
    assert len(lines) == 2
    assert lines[0]["cites"] == [1]
    assert "Deploy" in lines[0]["text"]
    assert "#" not in lines[0]["text"]  # no invented numbers for the verifier


def test_graph_runs_with_model_off(captures, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("cdesk.graphs.journal.chat", boom)
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-14", "kind": "daily", "captures": captures})
    assert result["used_fallback"] is True
    assert len(result["lines"]) == 2
    assert all(ln["cites"] for ln in result["lines"])
    assert result["bad"] == {}


# --- select trims for the prompt, verify checks full bodies (#12) ----------

def test_select_trims_long_bodies():
    long = [{"id": 1, "origin": "x", "title": "t", "body": "a" * 5000}]
    out = select({"captures": long})
    assert len(out["trimmed"][0]["body"]) < 5000
    assert out["trimmed"][0]["body"].endswith("…[trimmed]")
    assert len(long[0]["body"]) == 5000  # original capture untouched


def test_verify_passes_clean_llm_line(captures, monkeypatch):
    def fake_chat(messages, model, schema, temperature=0.0):
        assert schema is JournalLines
        return JournalLines(lines=[{"text": "Shipped v2 on 4 Nov.", "cites": [1]}])
    monkeypatch.setattr("cdesk.graphs.journal.chat", fake_chat)
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-14", "kind": "daily", "captures": captures})
    assert result["used_fallback"] is False
    assert result["attempt"] == 1
    assert result["lines"][0]["text"] == "Shipped v2 on 4 Nov."
    assert result["bad"] == {}


# --- verify, retry, drop-and-warn (#14) -------------------------------------

def test_invented_number_is_retried_then_fixed(captures, monkeypatch):
    calls = {"n": 0}

    def fake_chat(messages, model, schema, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return JournalLines(lines=[{"text": "Shipped v2 to 99 users on 4 Nov.", "cites": [1]}])
        return JournalLines(lines=[{"text": "Shipped v2 on 4 Nov.", "cites": [1]}])
    monkeypatch.setattr("cdesk.graphs.journal.chat", fake_chat)
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-14", "kind": "daily", "captures": captures})
    assert calls["n"] == 2
    assert result["attempt"] == 2
    assert result["bad"] == {}
    assert "99 users" not in result["lines"][0]["text"]


def test_persistent_bad_line_dropped_with_warning(captures, monkeypatch):
    def always_bad(messages, model, schema, temperature=0.0):
        return JournalLines(lines=[{"text": "Invented 42 things", "cites": [1]}])
    monkeypatch.setattr("cdesk.graphs.journal.chat", always_bad)
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-14", "kind": "daily", "captures": captures})
    assert result["lines"] == []
    assert any("dropped unsupported line" in w for w in result["warnings"])
    assert any("number 42" in w for w in result["warnings"])


def test_router_respects_max_attempts():
    assert journal_router({"bad": {0: ["x"]}, "attempt": 0}) == "summarize"
    assert journal_router({"bad": {0: ["x"]}, "attempt": MAX_ATTEMPTS}) == "store"
    assert journal_router({"bad": {}, "attempt": 0}) == "store"


def test_retry_prompt_carries_feedback(captures, monkeypatch):
    seen = []

    def fake_chat(messages, model, schema, temperature=0.0):
        seen.append(messages[0]["content"])
        if len(seen) == 1:
            return JournalLines(lines=[{"text": "Closed 99 PRs", "cites": [1]}])
        return JournalLines(lines=[{"text": "Shipped v2 on 4 Nov.", "cites": [1]}])
    monkeypatch.setattr("cdesk.graphs.journal.chat", fake_chat)
    g = build_journal_graph()
    g.invoke({"day": "2026-10-14", "kind": "daily", "captures": captures})
    assert "99" in seen[1]
    assert "number 42" not in seen[1]


# --- store to db (#12) ------------------------------------------------------

def test_store_writes_entry_and_lines(captures, conn):
    result = store({
        "day": "2026-10-14", "kind": "daily", "captures": captures, "conn": conn,
        "lines": [{"text": "Shipped v2 on 4 Nov.", "cites": [1]}],
    })
    entry_id = result["entry_id"]
    assert entry_id > 0
    entry = conn.execute("SELECT * FROM journal_entry WHERE id=?", (entry_id,)).fetchone()
    assert entry["day"] == "2026-10-14"
    assert entry["status"] == "draft"
    line = conn.execute("SELECT * FROM journal_line WHERE entry_id=?", (entry_id,)).fetchone()
    assert line["text"] == "Shipped v2 on 4 Nov."
    assert json.loads(line["capture_ids"]) == [1]


def test_graph_end_to_end_stores_to_db(captures, conn, monkeypatch):
    def fake_chat(messages, model, schema, temperature=0.0):
        return JournalLines(lines=[{"text": "Shipped v2 on 4 Nov.", "cites": [1]}])
    monkeypatch.setattr("cdesk.graphs.journal.chat", fake_chat)
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-14", "kind": "daily", "captures": captures, "conn": conn})
    assert result["entry_id"] > 0
    rows = conn.execute("SELECT COUNT(*) FROM journal_line").fetchone()[0]
    assert rows == 1


def test_empty_captures_warns(capsys):
    result = store({"day": "2026-10-14", "kind": "daily", "captures": [], "lines": []})
    assert any("no captures" in w for w in result["warnings"])


# --- weekly digest (#17) ----------------------------------------------------

def test_weekly_fallback_groups_by_day(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr("cdesk.graphs.journal.chat", boom)
    source_lines = [
        {"id": 10, "text": "Shipped v2 on 4 Nov.", "capture_ids": [1], "day": "2026-10-13"},
        {"id": 11, "text": "Fixed the watcher race.", "capture_ids": [2], "day": "2026-10-14"},
        {"id": 12, "text": "Reviewed the schema.", "capture_ids": [3], "day": "2026-10-14"},
    ]
    captures = [
        {"id": 1, "origin": "a", "title": "", "body": "Shipped v2 on 4 Nov."},
        {"id": 2, "origin": "b", "title": "", "body": "Fixed the watcher race."},
        {"id": 3, "origin": "c", "title": "", "body": "Reviewed the schema."},
    ]
    g = build_journal_graph()
    result = g.invoke({
        "day": "2026-10-13", "kind": "weekly",
        "captures": captures, "source_lines": source_lines,
    })
    assert result["used_fallback"] is True
    assert len(result["lines"]) == 2  # one per day
    assert "Shipped v2 on 4 Nov." in result["lines"][0]["text"]
    assert result["lines"][1]["cites"] == [2, 3]
    assert result["bad"] == {}


def test_weekly_llm_path_includes_daily_lines(monkeypatch):
    seen = []

    def fake_chat(messages, model, schema, temperature=0.0):
        seen.append(messages[0]["content"])
        return JournalLines(lines=[{"text": "Fixed the watcher race.", "cites": [2]}])
    monkeypatch.setattr("cdesk.graphs.journal.chat", fake_chat)
    captures = [{"id": 2, "origin": "b", "title": "", "body": "Fixed the watcher race."}]
    g = build_journal_graph()
    result = g.invoke({
        "day": "2026-10-13", "kind": "weekly",
        "captures": captures,
        "source_lines": [{"id": 11, "text": "Fixed the watcher race.", "capture_ids": [2], "day": "2026-10-14"}],
    })
    assert "Fixed the watcher race." in seen[0]
    assert result["lines"][0]["cites"] == [2]
