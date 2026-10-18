"""Job tailor graph tests: parse_jd, match_evidence, write_bullets, citation
verify, cover letter. M6 issues #40, #41.
"""

import json
from datetime import date

import numpy as np
import pytest

from cdesk.config import MAX_ATTEMPTS
from cdesk.graphs.job_tailor import (
    Bullet,
    Bullets,
    Requirement,
    Requirements,
    build_job_tailor_graph,
    draft_cover_letter,
    evidence_pool,
    fallback_bullets,
    flatten_evidence,
    match_evidence,
    parse_jd,
    tailor_router,
    template_cover_letter,
    verify,
    verify_bullets,
    write_bullets,
)


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def job(conn):
    from cdesk.jobs import add_job
    return add_job(conn, "Acme", "Backend Engineer",
                   jd_text="Python and SQLite. 3 years experience. https://acme.dev/apply")


def _approved_entry(conn, day, lines):
    from cdesk.db import store_journal_entry
    entry_id = store_journal_entry(
        conn, day, "daily",
        [{"text": t, "cites": [1]} for t in lines],
    )
    conn.execute("UPDATE journal_entry SET status = 'approved' WHERE id = ?", (entry_id,))
    conn.commit()
    return entry_id


# --- parse_jd (#40) ------------------------------------------------------------

def test_parse_jd_structured_output(conn, job, monkeypatch):
    def fake_chat(messages, model, schema=None, temperature=0.0):
        assert "Python and SQLite" in messages[0]["content"]
        return Requirements(requirements=[
            Requirement(text="Python"),
            Requirement(text="SQLite"),
        ])
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    out = parse_jd({"conn": conn, "job_id": job["id"]})
    assert [r["text"] for r in out["requirements"]] == ["Python", "SQLite"]
    assert out["used_fallback"] is False
    assert out["jd_text"] == job["jd_text"]


def test_parse_jd_fallback_splits_lines(conn, job, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model off")
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", boom)
    out = parse_jd({
        "conn": conn, "job_id": job["id"],
        "jd_text": "Python backend engineer\nExperience with SQLite\n3+ years shipping APIs",
    })
    assert out["used_fallback"] is True
    assert len(out["requirements"]) >= 2
    assert all(len(r["text"]) >= 8 for r in out["requirements"])


# --- match_evidence (#40) ---------------------------------------------------------

class FakeEmbedder:
    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, texts):
        return [self.mapping[t] for t in texts]


def test_match_evidence_top_k_by_cosine():
    pool = [
        {"id": 1, "text": "Python SQLite work", "day": "2026-10-01", "capture_ids": []},
        {"id": 2, "text": "Cooked pasta", "day": "2026-10-02", "capture_ids": []},
        {"id": 3, "text": "SQLite tuning", "day": "2026-10-03", "capture_ids": []},
    ]
    embedder = FakeEmbedder({
        "Python experience": [1.0, 0.0],
        "Python SQLite work": [0.9, 0.1],
        "Cooked pasta": [0.0, 1.0],
        "SQLite tuning": [0.8, 0.2],
    })
    out = match_evidence([{"text": "Python experience"}], pool, k=2, embedder=embedder)
    assert [m["id"] for m in out[0]["matches"]] == [1, 3]
    assert out[0]["matches"][0]["score"] >= out[0]["matches"][1]["score"]


def test_match_evidence_keyword_fallback_when_embedder_down():
    pool = [
        {"id": 1, "text": "Shipped the SQLite cache layer", "day": "2026-10-01", "capture_ids": []},
        {"id": 2, "text": "Wrote a blog post about hiking", "day": "2026-10-02", "capture_ids": []},
    ]

    def boom(texts):
        raise RuntimeError("ollama down")

    out = match_evidence([{"text": "SQLite cache"}], pool, embedder=boom)
    assert [m["id"] for m in out[0]["matches"]] == [1]
    assert out[0]["matches"][0]["score"] > 0


def test_match_evidence_empty_requirements_or_pool():
    assert match_evidence([], [{"id": 1, "text": "x", "day": "d"}]) == []
    out = match_evidence([{"text": "x"}], [])
    assert out == [{"requirement": "x", "matches": []}]


def test_flatten_evidence_dedupe_best_score_first():
    matched = [
        {"requirement": "a", "matches": [
            {"id": 1, "text": "one", "day": "d", "score": 0.5},
            {"id": 2, "text": "two", "day": "d", "score": 0.9},
        ]},
        {"requirement": "b", "matches": [
            {"id": 1, "text": "one", "day": "d", "score": 0.7},
        ]},
    ]
    flat = flatten_evidence(matched)
    assert [e["id"] for e in flat] == [2, 1]
    assert flat[1]["score"] == 0.7  # kept the best score for id 1


# --- evidence pool (#40) -----------------------------------------------------------

def test_evidence_pool_prefers_approved(conn):
    _approved_entry(conn, "2026-10-01", ["Approved line A"])
    from cdesk.db import store_journal_entry
    store_journal_entry(conn, "2026-10-02", "daily",
                        [{"text": "Draft line B", "cites": [1]}])
    pool = evidence_pool(conn)
    assert [p["text"] for p in pool] == ["Approved line A"]


def test_evidence_pool_falls_back_to_draft_lines(conn):
    from cdesk.db import store_journal_entry
    store_journal_entry(conn, "2026-10-02", "daily",
                        [{"text": "Only a draft line", "cites": [1]}])
    pool = evidence_pool(conn)
    assert [p["text"] for p in pool] == ["Only a draft line"]


# --- verify_bullets: planted-error tests (#40, #41) -------------------------

EVIDENCE = {
    10: {"title": None, "body": "Shipped the SQLite cache on 4 Nov. https://example.com/r"},
    11: {"title": None, "body": "Reviewed 3 PRs from the team."},
}


def test_verify_bullets_clean_pass():
    bullets = [{"text": "Shipped the SQLite cache on 4 Nov.", "cites": [10]}]
    assert verify_bullets(bullets, EVIDENCE) == {}


def test_verify_bullets_missing_citation_planted_error():
    bullets = [{"text": "Shipped the cache", "cites": []}]
    bad = verify_bullets(bullets, EVIDENCE)
    assert 0 in bad
    assert "no citation" in bad[0]


def test_verify_bullets_unknown_citation_planted_error():
    bullets = [{"text": "Shipped the cache", "cites": [999]}]
    bad = verify_bullets(bullets, EVIDENCE)
    assert "cites an unknown capture id" in bad[0]


def test_verify_bullets_invented_number_planted_error():
    bullets = [{"text": "Shipped 5 caches on 4 Nov.", "cites": [10]}]
    bad = verify_bullets(bullets, EVIDENCE)
    assert any("number 5" in r for r in bad[0])


def test_verify_bullets_invented_url_planted_error():
    bullets = [{"text": "Wrote it up at https://fake.example.com", "cites": [10]}]
    bad = verify_bullets(bullets, EVIDENCE)
    assert any("url" in r for r in bad[0])


def test_verify_bullets_one_bad_one_good():
    bullets = [
        {"text": "Reviewed 3 PRs from the team.", "cites": [11]},
        {"text": "Reviewed 9 PRs.", "cites": [11]},
    ]
    bad = verify_bullets(bullets, EVIDENCE)
    assert 0 not in bad
    assert 1 in bad


# --- write_bullets with retry feedback (#40) ----------------------------------------

def test_write_bullets_builds_prompt_with_evidence(conn, monkeypatch):
    seen = {}

    def fake_chat(messages, model, schema=None, temperature=0.0):
        seen["prompt"] = messages[0]["content"]
        return Bullets(bullets=[])
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    write_bullets({
        "requirements": [{"text": "Python"}],
        "evidence": [{"id": 10, "text": "line", "day": "2026-10-01", "score": 0.9}],
        "attempt": 0,
    })
    assert "[10]" in seen["prompt"]
    assert "Python" in seen["prompt"]


def test_write_bullets_retry_carries_exact_violations(conn, monkeypatch):
    prompts = []

    def fake_chat(messages, model, schema=None, temperature=0.0):
        prompts.append(messages[0]["content"])
        return Bullets(bullets=[])
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    write_bullets({
        "requirements": [{"text": "Python"}],
        "evidence": [{"id": 10, "text": "line", "day": "d", "score": 0.9}],
        "bullets": [{"text": "Shipped 5 caches", "cites": [10]}],
        "bad": {0: ["number 5 not in cited captures"]},
        "attempt": 1,
    })
    assert "number 5 not in cited captures" in prompts[0]
    assert "never invent" in prompts[0].lower()


def test_fallback_bullets_quote_top_matches():
    state = {"matched": [
        {"requirement": "a", "matches": [{"id": 1, "text": "first line", "day": "d", "score": 0.9}]},
        {"requirement": "b", "matches": [{"id": 2, "text": "second line", "day": "d", "score": 0.8}]},
        {"requirement": "c", "matches": []},
    ]}
    bullets = fallback_bullets(state)
    assert bullets == [
        {"text": "first line", "cites": [1]},
        {"text": "second line", "cites": [2]},
    ]


# --- full graph: retry then clean save (#40) ------------------------------------------

def test_graph_invented_bullet_retried_then_clean(conn, job, monkeypatch):
    _approved_entry(conn, "2026-10-01", ["Shipped the SQLite cache on 4 Nov."])
    calls = {"n": 0}

    def fake_chat(messages, model, schema=None, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:  # parse_jd
            return Requirements(requirements=[Requirement(text="SQLite")])
        if calls["n"] == 2:  # write_bullets: invented date
            return Bullets(bullets=[Bullet(text="Shipped it on 14 Nov.", cites=[1])])
        return Bullets(bullets=[Bullet(text="Shipped the SQLite cache on 4 Nov.", cites=[1])])
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    result = build_job_tailor_graph().invoke({
        "conn": conn, "job_id": job["id"], "jd_text": job["jd_text"],
        "company": job["company"], "role": job["role"],
    })
    assert calls["n"] == 3  # parse + bad write + fixed write
    assert result["bad"] == {}
    assert result["warnings"] == []
    from cdesk.db import connect  # ensure artifact table exists
    row = conn.execute("SELECT * FROM job_artifact WHERE job_id = ?",
                       (job["id"],)).fetchone()
    assert row["kind"] == "bullets"
    assert "4 Nov" in row["body"]
    assert json.loads(row["citations"])[0]["cites"] == [1]


def test_graph_persistent_bad_bullets_dropped_with_warnings(conn, job, monkeypatch):
    _approved_entry(conn, "2026-10-01", ["Reviewed 3 PRs from the team."])

    def fake_chat(messages, model, schema=None, temperature=0.0):
        if isinstance(schema, type) and schema is Requirements:
            return Requirements(requirements=[Requirement(text="Reviews")])
        return Bullets(bullets=[Bullet(text="Reviewed 9 PRs.", cites=[1])])
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    result = build_job_tailor_graph().invoke({
        "conn": conn, "job_id": job["id"], "jd_text": job["jd_text"],
        "company": job["company"], "role": job["role"],
    })
    assert result["bullets"] == []  # the one bad bullet was dropped
    assert any("dropped unsupported bullet" in w for w in result["warnings"])
    row = conn.execute("SELECT * FROM job_artifact WHERE job_id = ?",
                       (job["id"],)).fetchone()
    assert json.loads(row["warnings"])


def test_router_respects_max_attempts():
    assert tailor_router({"bad": {0: ["x"]}, "attempt": 0}) == "write_bullets"
    assert tailor_router({"bad": {0: ["x"]}, "attempt": MAX_ATTEMPTS}) == "save"
    assert tailor_router({"bad": {}, "attempt": 0}) == "save"


def test_graph_with_model_off_uses_fallback(conn, job, monkeypatch):
    _approved_entry(conn, "2026-10-01", ["Shipped the SQLite cache on 4 Nov."])

    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", boom)
    result = build_job_tailor_graph().invoke({
        "conn": conn, "job_id": job["id"], "jd_text": job["jd_text"],
        "company": job["company"], "role": job["role"],
    })
    assert result["used_fallback"] is True
    assert any("template fallback" in w for w in result["warnings"])
    # fallback bullets quote journal lines verbatim, so citations survive
    assert result["bad"] == {}
    assert result["bullets"][0]["text"] == "Shipped the SQLite cache on 4 Nov."


# --- cover letter (#41) --------------------------------------------------------------

def test_cover_letter_grounded_and_stored(conn, job, monkeypatch):
    _approved_entry(conn, "2026-10-01", ["Shipped the SQLite cache on 4 Nov."])
    calls = {"n": 0}

    def fake_chat(messages, model, schema=None, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:  # parse_jd
            return Requirements(requirements=[Requirement(text="SQLite")])
        return ("Dear Acme team, I shipped the SQLite cache on 4 Nov. "
                "Sincerely")
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    out = draft_cover_letter(conn, job["id"])
    assert out["letter"].startswith("Dear Acme team")
    assert out["warnings"] == []
    assert out["citations"]  # matched journal line ids
    row = conn.execute("SELECT * FROM job_artifact WHERE kind = 'cover'").fetchone()
    assert row["job_id"] == job["id"]
    assert "4 Nov" in row["body"]


def test_cover_letter_invented_date_retried(conn, job, monkeypatch):
    _approved_entry(conn, "2026-10-01", ["Shipped the SQLite cache on 4 Nov."])
    calls = {"n": 0}

    def fake_chat(messages, model, schema=None, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return Requirements(requirements=[Requirement(text="SQLite")])
        if calls["n"] == 2:
            return "I shipped things on 14 Nov. Sincerely"  # invented
        return "I shipped the SQLite cache on 4 Nov. Sincerely"
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", fake_chat)
    out = draft_cover_letter(conn, job["id"])
    assert calls["n"] == 3
    assert out["warnings"] == []
    assert "4 Nov" in out["letter"]


def test_cover_letter_fallback_passes_fact_check(conn, job, monkeypatch):
    _approved_entry(conn, "2026-10-01", ["Shipped the SQLite cache on 4 Nov."])

    def boom(*a, **k):
        raise RuntimeError("model off")
    monkeypatch.setattr("cdesk.graphs.job_tailor.chat", boom)
    out = draft_cover_letter(conn, job["id"])
    assert out["used_fallback"] is True
    assert any("template fallback" in w for w in out["warnings"])
    from cdesk.verify import check_facts
    # fact check against jd + evidence (the source the letter may use)
    source = job["jd_text"] + "\nShipped the SQLite cache on 4 Nov."
    assert check_facts(out["letter"], source) == []


def test_cover_letter_missing_job(conn):
    with pytest.raises(ValueError):
        draft_cover_letter(conn, 999)


def test_template_cover_letter_is_grounded():
    state = {
        "company": "Acme", "role": "Backend Engineer",
        "requirements": [{"text": "Python"}],
        "evidence": [{"text": "Built the ingestion pipeline", "id": 1, "day": "d"}],
    }
    letter = template_cover_letter(state)
    assert "Acme" in letter
    assert "Built the ingestion pipeline" in letter
    assert check_facts_free(letter)


def check_facts_free(letter: str) -> bool:
    from cdesk.verify import extract_facts
    return not extract_facts(letter)
