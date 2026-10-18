"""Draft graph tests: gather, write+retry, checks, fallback, save, repurpose.
M4 issues #23, #24, #27, #28, #29.
"""

import json

import pytest

from cdesk.config import MAX_ATTEMPTS
from cdesk.graphs.draft import (
    build_draft_graph,
    draft_router,
    gather,
    save,
)


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def ws(conn):
    from cdesk.workspaces import create_workspace
    return create_workspace(conn, "LI", kind="linkedin")


SOURCE = "Shipped v2 on 4 Nov. See https://example.com/r"


# --- gather (#23) -----------------------------------------------------------

def test_gather_freeform_uses_brief(conn, ws):
    out = gather({"conn": conn, "workspace_id": ws["id"],
                  "source_kind": "freeform", "brief": "announce the workshop"})
    assert out["source_text"] == "announce the workshop"
    assert out["rules"]["max_chars"] == 3000  # loaded from workspace kind


def test_gather_journal_uses_entry_lines(conn, ws):
    from cdesk.db import store_journal_entry
    entry_id = store_journal_entry(
        conn, "2026-10-14", "daily",
        [{"text": "Shipped v2 on 4 Nov.", "cites": [1]}],
    )
    out = gather({"conn": conn, "workspace_id": ws["id"],
                  "source_kind": "journal", "source_ids": [entry_id]})
    assert "Shipped v2 on 4 Nov." in out["source_text"]


def test_gather_post_uses_post_body(conn, ws):
    from cdesk.db import store_post
    post_id = store_post(conn, ws["id"], SOURCE, status="published")
    out = gather({"conn": conn, "workspace_id": ws["id"],
                  "source_kind": "post", "source_ids": [post_id]})
    assert "Shipped v2 on 4 Nov." in out["source_text"]


def test_gather_idea_uses_title_and_note(conn, ws):
    conn.execute("INSERT INTO idea (title, note) VALUES (?, ?)",
                 ("Faster builds", "Cut CI to 4 min with a cache."))
    idea_id = conn.execute("SELECT id FROM idea").fetchone()["id"]
    out = gather({"conn": conn, "workspace_id": ws["id"],
                  "source_kind": "idea", "source_ids": [idea_id]})
    assert "Faster builds" in out["source_text"]
    assert "4 min" in out["source_text"]


# --- voice node -------------------------------------------------------------

def test_voice_survives_ollama_down(conn, ws, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("cdesk.graphs.draft.voice_examples", boom)
    out = gather({"conn": conn, "workspace_id": ws["id"],
                  "source_kind": "freeform", "brief": "x"})
    from cdesk.graphs.draft import voice
    result = voice({**out, "conn": conn, "workspace_id": ws["id"], "source_text": "x"})
    assert result["voice_examples"] == []


# --- write with retry feedback (#24) ----------------------------------------

def test_write_builds_prompt_with_rules_and_source(conn, ws, monkeypatch):
    seen = {}

    def fake_chat(messages, model, schema=None, temperature=0.0):
        seen["prompt"] = messages[0]["content"]
        return "Shipped v2 on 4 Nov."
    monkeypatch.setattr("cdesk.graphs.draft.chat", fake_chat)
    from cdesk.graphs.draft import write
    out = write({"conn": conn, "workspace_id": ws["id"],
                 "source_text": SOURCE, "brief": "announce v2",
                 "platform": "linkedin", "rules": {"max_chars": 3000},
                 "voice_examples": ["example one"]})
    assert out["draft"] == "Shipped v2 on 4 Nov."
    assert out["used_fallback"] is False
    assert out["attempt"] == 1
    assert "linkedin" in seen["prompt"]
    assert SOURCE in seen["prompt"]
    assert "example one" in seen["prompt"]


def test_retry_prompt_carries_exact_violations(conn, ws, monkeypatch):
    prompts = []

    def fake_chat(messages, model, schema=None, temperature=0.0):
        prompts.append(messages[0]["content"])
        return "Draft text"
    monkeypatch.setattr("cdesk.graphs.draft.chat", fake_chat)
    from cdesk.graphs.draft import write
    write({"conn": conn, "workspace_id": ws["id"], "source_text": SOURCE,
           "platform": "linkedin", "rules": {},
           "violations": ["not in source: 14-nov"], "attempt": 1})
    assert "not in source: 14-nov" in prompts[0]
    assert "never invent" in prompts[0].lower()


# --- full loop: violation caught, retried, fixed (#24, #27) -----------------

def test_invented_date_is_retried_then_fixed(conn, ws, monkeypatch):
    calls = {"n": 0}

    def fake_chat(messages, model, schema=None, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return "Workshop on 14 Nov at 3:30 pm."
        return "Workshop on 4 Nov at 3:30 pm."
    monkeypatch.setattr("cdesk.graphs.draft.chat", fake_chat)
    g = build_draft_graph()
    result = g.invoke({"conn": conn, "workspace_id": ws["id"],
                       "source_kind": "freeform",
                       "source_text": "Workshop on 4 Nov at 3:30 pm.",
                       "platform": "linkedin"})
    assert calls["n"] == 2
    assert result["attempt"] == 2
    assert result["violations"] == []
    assert result["draft"] == "Workshop on 4 Nov at 3:30 pm."
    from cdesk.db import get_post
    post = get_post(conn, result["post_id"])
    assert post["warnings"] in (None, "[]", "")


def test_router_respects_max_attempts():
    assert draft_router({"violations": ["x"], "attempt": 0}) == "write"
    assert draft_router({"violations": ["x"], "attempt": MAX_ATTEMPTS}) == "save"
    assert draft_router({"violations": [], "attempt": 0}) == "save"


# --- persistent violations: saved with warnings (#27) -----------------------

def test_persistent_violations_saved_with_warnings(conn, ws, monkeypatch):
    def always_bad(messages, model, schema=None, temperature=0.0):
        return "Workshop on 14 Nov."
    monkeypatch.setattr("cdesk.graphs.draft.chat", always_bad)
    g = build_draft_graph()
    result = g.invoke({"conn": conn, "workspace_id": ws["id"],
                       "source_kind": "freeform",
                       "source_text": "Workshop on 4 Nov.",
                       "platform": "linkedin"})
    assert result["post_id"] > 0
    from cdesk.db import get_post
    post = get_post(conn, result["post_id"])
    warnings = json.loads(post["warnings"])
    assert any("14-nov" in w for w in warnings)
    assert post["status"] == "draft"


def test_banned_phrase_flagged_by_rules_check(conn, ws, monkeypatch):
    from cdesk.workspaces import add_banned_phrase
    add_banned_phrase(conn, ws["id"], "game-changer")
    monkeypatch.setattr("cdesk.graphs.draft.chat", lambda *a, **k: "This is a game-changer for us.")
    g = build_draft_graph()
    result = g.invoke({"conn": conn, "workspace_id": ws["id"],
                       "source_kind": "freeform", "source_text": "We shipped v2.",
                       "platform": "linkedin"})
    assert any("game-changer" in w for w in result["warnings"])


# --- template fallback (#28) ------------------------------------------------

def test_graph_runs_with_model_off(conn, ws, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("cdesk.graphs.draft.chat", boom)
    g = build_draft_graph()
    result = g.invoke({"conn": conn, "workspace_id": ws["id"],
                       "source_kind": "freeform", "source_text": SOURCE,
                       "platform": "linkedin"})
    assert result["used_fallback"] is True
    assert SOURCE in result["draft"]
    assert result["post_id"] > 0


def test_template_fallback_invents_nothing(conn, ws, monkeypatch):
    from cdesk.verify import check_facts
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr("cdesk.graphs.draft.chat", boom)
    g = build_draft_graph()
    result = g.invoke({"conn": conn, "workspace_id": ws["id"],
                       "source_kind": "freeform", "source_text": SOURCE,
                       "platform": "linkedin"})
    assert check_facts(result["draft"], SOURCE) == []


# --- save and repurpose (#29) -----------------------------------------------

def test_save_records_source_ids(conn, ws, monkeypatch):
    monkeypatch.setattr("cdesk.graphs.draft.chat",
                        lambda *a, **k: "Clean draft without numbers.")
    g = build_draft_graph()
    result = g.invoke({"conn": conn, "workspace_id": ws["id"],
                       "source_kind": "freeform", "source_text": "No digits here.",
                       "brief": "say something", "platform": "linkedin"})
    from cdesk.db import get_post
    post = get_post(conn, result["post_id"])
    assert post["workspace_id"] == ws["id"]
    assert json.loads(post["source_ids"]) == {"kind": "freeform", "ids": []}


def test_repurpose_creates_child_in_other_workspace(conn, ws, monkeypatch):
    from cdesk.db import get_post, store_post
    from cdesk.workspaces import create_workspace
    from cdesk.graphs.draft import repurpose_post
    parent_id = store_post(conn, ws["id"], SOURCE, status="draft")
    other = create_workspace(conn, "Sub", kind="substack")
    monkeypatch.setattr("cdesk.graphs.draft.chat",
                        lambda *a, **k: "Same facts, new channel.")
    result = repurpose_post(conn, parent_id, other["id"])
    child = get_post(conn, result["post_id"])
    assert child["workspace_id"] == other["id"]
    assert child["parent_post_id"] == parent_id
    assert child["body_md"] == "Same facts, new channel."
    assert "4 Nov" in get_post(conn, parent_id)["body_md"]  # parent untouched


def test_save_without_conn_returns_zero_post_id():
    out = save({"draft": "x", "violations": [], "source_ids": [],
                "workspace_id": 1})
    assert out["post_id"] == 0
