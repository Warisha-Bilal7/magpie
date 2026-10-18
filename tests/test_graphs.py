from cdesk.config import MAX_ATTEMPTS
from cdesk.graphs.draft import build_draft_graph
from cdesk.graphs.journal import build_journal_graph
from cdesk.graphs.job_tailor import build_job_tailor_graph


def test_journal_graph_runs_with_stub_captures():
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


def test_journal_verify_drops_uncited_lines():
    from cdesk.graphs.journal import verify

    out = verify({"lines": [{"text": "made up", "cites": []},
                            {"text": "real", "cites": [1]}]})
    assert out["lines"] == [{"text": "real", "cites": [1]}]
    assert any("dropped 1" in w for w in out["warnings"])


def test_journal_graph_empty_captures():
    g = build_journal_graph()
    result = g.invoke({"day": "2026-10-18", "kind": "daily", "captures": []})
    assert result["lines"] == []


def test_draft_graph_runs_end_to_end():
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


def test_job_tailor_graph_runs_end_to_end():
    g = build_job_tailor_graph()
    result = g.invoke({"jd_text": "Python experience\nSQL skills"})
    assert len(result["bullets"]) == 2
    assert result["used_fallback"] is True
