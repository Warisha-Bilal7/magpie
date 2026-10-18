from cdesk.config import MAX_ATTEMPTS
from cdesk.graphs.draft import build_draft_graph
from cdesk.graphs.journal import build_journal_graph
from cdesk.graphs.job_tailor import build_job_tailor_graph


def test_journal_graph_runs_with_stub_captures(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model off")
    monkeypatch.setattr("cdesk.graphs.journal.chat", boom)
    g = build_journal_graph()
    result = g.invoke({
        "day": "2026-10-18",
        "kind": "daily",
        "captures": [
            {"id": 1, "origin": "opencode", "title": "fixed the FTS bug", "body": "..."},
            {"id": 2, "origin": "gemini", "title": "planned the talk", "body": "..."},
        ],
    })
    assert len(result["lines"]) == 2
    assert all(ln["cites"] for ln in result["lines"])
    assert result["used_fallback"] is True


def test_journal_verify_flags_uncited_lines():
    from cdesk.graphs.journal import verify

    out = verify({
        "captures": [{"id": 1, "origin": "x", "title": "t", "body": "b"}],
        "lines": [{"text": "made up", "cites": []}, {"text": "real", "cites": [1]}],
    })
    assert 0 in out["bad"]
    assert 1 not in out["bad"]


def test_journal_graph_empty_captures():
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-18", "kind": "daily", "captures": []})
    assert result["lines"] == []


def test_draft_graph_runs_end_to_end(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model off")
    monkeypatch.setattr("cdesk.graphs.draft.chat", boom)
    g = build_draft_graph()
    result = g.invoke({
        "brief": "announce the workshop on 4 Nov",
        "source_kind": "freeform",
        "rules": {"max_chars": 3000, "max_hashtags": 5, "banned": []},
    })
    assert "announce the workshop on 4 Nov" in result["draft"]
    assert result["used_fallback"] is True
    assert result["post_id"] == 0


def test_draft_router_saves_when_clean():
    from cdesk.graphs.draft import draft_router

    assert draft_router({"violations": []}) == "save"
    assert draft_router({"violations": ["x"], "attempt": 1}) == "write"
    assert draft_router({"violations": ["x"], "attempt": MAX_ATTEMPTS}) == "save"


def test_job_tailor_graph_runs_end_to_end(monkeypatch):
    from cdesk.db import init_db, store_journal_entry
    from cdesk.jobs import add_job

    conn = init_db(":memory:")
    entry_id = store_journal_entry(conn, "2026-10-01", "daily", [
        {"text": "Shipped the Python SQLite cache", "cites": [1]},
        {"text": "Tuned SQL skills on the query planner", "cites": [1]},
    ])
    conn.execute("UPDATE journal_entry SET status = 'approved' WHERE id = ?",
                 (entry_id,))
    conn.commit()
    job = add_job(conn, "Acme", "Backend Engineer", jd_text="Python experience\nSQL skills")

    def boom(*a, **k):
        raise RuntimeError("model off")
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", boom)

    g = build_job_tailor_graph()
    result = g.invoke({
        "conn": conn, "job_id": job["id"], "jd_text": job["jd_text"],
        "company": job["company"], "role": job["role"],
    })
    assert len(result["bullets"]) == 2  # one verbatim quote per requirement
    assert result["used_fallback"] is True
