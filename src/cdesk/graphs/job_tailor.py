"""Job tailor graph: parse_jd -> match_evidence -> write_bullets -> verify -> store.

The model extracts requirements and drafts bullets; deterministic code matches
journal evidence by embedding similarity (keyword overlap when Ollama is down)
and verifies every bullet with the same citation check the journal uses —
numbers, dates and URLs must exist in the cited lines. Bullets that stay
unsupported after MAX_ATTEMPTS are dropped with a warning (docs/PLAN.md F10,
issues #40, #41).
"""

import json
import operator
import re
from datetime import datetime, timezone
from typing import Annotated, Literal, TypedDict

import numpy as np
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..config import JOURNAL_TEMPERATURE, MAX_ATTEMPTS, MODEL_NAME, PROMPTS_DIR
from ..jobs import get_job
from ..llm import chat
from ..verify import check_facts, unsupported_reasons
from ..voice import embed_texts, top_k

# How many journal lines to retrieve per requirement.
EVIDENCE_K = 3


class Requirement(BaseModel):
    text: str


class Requirements(BaseModel):
    requirements: list[Requirement]


class Bullet(BaseModel):
    text: str
    cites: list[int]


class Bullets(BaseModel):
    bullets: list[Bullet]


class JobTailorState(TypedDict, total=False):
    conn: object
    job_id: int
    jd_text: str
    company: str
    role: str
    model_name: str
    requirements: list[dict]        # [{"text": ...}]
    matched: list[dict]             # per requirement: {"requirement", "matches"}
    evidence: list[dict]            # flat unique lines {"id", "text", "day", "score"}
    bullets: list[dict]             # [{"text", "cites"}]
    bad: dict[int, list[str]]       # bullet index -> reasons
    attempt: int
    artifact_id: int
    used_fallback: bool
    warnings: Annotated[list[str], operator.add]


# --- deterministic pieces (no model) ----------------------------------------

def evidence_pool(conn, limit: int = 40) -> list[dict]:
    """Verified journal lines to ground bullets in. Prefers approved entries;
    falls back to any journal line so dogfooding works before approval."""
    rows = conn.execute(
        """SELECT jl.id, jl.text, jl.capture_ids, je.day
           FROM journal_line jl
           JOIN journal_entry je ON je.id = jl.entry_id
           WHERE je.status = 'approved'
           ORDER BY je.day DESC, jl.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """SELECT jl.id, jl.text, jl.capture_ids, je.day
               FROM journal_line jl
               JOIN journal_entry je ON je.id = jl.entry_id
               ORDER BY je.day DESC, jl.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _keyword_matches(req_text: str, pool: list[dict], k: int) -> list[dict]:
    """Fallback matcher: word overlap, best first. No model needed."""
    req_tokens = _tokens(req_text)
    if not req_tokens:
        return []
    scored = []
    for p in pool:
        overlap = len(req_tokens & _tokens(p["text"]))
        if overlap:
            scored.append((overlap / len(req_tokens), p))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [{"id": p["id"], "text": p["text"], "day": p["day"], "score": round(s, 3)}
            for s, p in scored[:k]]


def match_evidence(
    requirements: list[dict],
    pool: list[dict],
    k: int = EVIDENCE_K,
    embedder=None,
) -> list[dict]:
    """Top-k journal lines per requirement, by cosine similarity.

    Uses embeddings when available and falls back to keyword overlap when
    Ollama is down — tailoring always works, just less precisely.
    """
    embedder = embedder or embed_texts
    if not requirements:
        return []
    if not pool:
        return [{"requirement": r["text"], "matches": []} for r in requirements]
    try:
        req_vecs = np.asarray(embedder([r["text"] for r in requirements]),
                              dtype="float32")
        line_vecs = np.asarray(embedder([p["text"] for p in pool]),
                               dtype="float32")
    except Exception:
        return [{"requirement": r["text"],
                 "matches": _keyword_matches(r["text"], pool, k)}
                for r in requirements]
    mat = np.atleast_2d(line_vecs)
    out = []
    for req, rv in zip(requirements, req_vecs):
        indices = top_k(np.asarray(rv, dtype="float32"), mat, k=k)
        matches = [
            {"id": pool[i]["id"], "text": pool[i]["text"], "day": pool[i]["day"],
             "score": round(float(np.dot(mat[i], rv) / (
                 (np.linalg.norm(mat[i]) * np.linalg.norm(rv)) + 1e-9)), 3)}
            for i in indices
        ]
        out.append({"requirement": req["text"], "matches": matches})
    return out


def flatten_evidence(matched: list[dict]) -> list[dict]:
    """Unique evidence lines across all requirements, best score first."""
    best: dict[int, dict] = {}
    for m in matched:
        for match in m.get("matches", []):
            cur = best.get(match["id"])
            if cur is None or match["score"] > cur["score"]:
                best[match["id"]] = match
    return sorted(best.values(), key=lambda e: (-e["score"], e["id"]))


def fallback_bullets(state: JobTailorState) -> list[dict]:
    """One bullet per requirement, quoting its top matched line verbatim —
    grounded by construction, so the citation verifier passes."""
    bullets, seen = [], set()
    for m in state.get("matched", []):
        matches = m.get("matches", [])
        if not matches:
            continue
        top = matches[0]
        if top["text"] in seen:
            continue
        seen.add(top["text"])
        bullets.append({"text": top["text"], "cites": [top["id"]]})
    return bullets


def verify_bullets(bullets: list[dict], evidence_by_id: dict[int, dict]) -> dict:
    """Same citation check the journal uses: every line must cite evidence
    that supports its numbers and URLs. Returns bad index -> reasons."""
    bad: dict[int, list[str]] = {}
    for i, b in enumerate(bullets):
        reasons = unsupported_reasons(
            {"text": b["text"], "cites": b["cites"]}, evidence_by_id
        )
        if reasons:
            bad[i] = reasons
    return bad


def _feedback(state: JobTailorState) -> str:
    bad = state.get("bad") or {}
    if not bad:
        return ""
    bullets = state.get("bullets", [])
    rows = []
    for i, reasons in sorted(bad.items()):
        if i < len(bullets):
            rows.append(f"- \"{bullets[i]['text']}\" -> {'; '.join(reasons)}")
    if not rows:
        return ""
    return ("The previous attempt had problems. Fix them or OMIT the bullet; "
            "never invent facts:\n" + "\n".join(rows))


def _evidence_prompt(evidence: list[dict]) -> str:
    lines = "\n".join(
        f"[{e['id']}] ({e.get('day') or '?'}) {e['text']}" for e in evidence
    )
    allowed = [e["id"] for e in evidence]
    return f"{lines}\n\nOnly cite line ids from this list: {allowed}."


def _requirements_prompt(requirements: list[dict]) -> str:
    return "\n".join(f"- {r['text']}" for r in requirements) or "(none)"


# --- graph nodes --------------------------------------------------------------

def parse_jd(state: JobTailorState) -> dict:
    """Job description to requirements. Structured output; line-split fallback."""
    jd_text = state.get("jd_text") or ""
    if not jd_text and state.get("conn") and state.get("job_id"):
        job = get_job(state["conn"], state["job_id"])
        if job:
            jd_text = job.get("jd_text") or ""
            state = {**state, "jd_text": jd_text,
                     "company": state.get("company") or job.get("company", ""),
                     "role": state.get("role") or job.get("role", "")}
    model = state.get("model_name") or MODEL_NAME
    prompt = (PROMPTS_DIR / "jd.txt").read_text(encoding="utf-8").replace(
        "{jd_text}", jd_text
    )
    try:
        result = chat([{"role": "user", "content": prompt}], model=model,
                      schema=Requirements, temperature=JOURNAL_TEMPERATURE)
        requirements = [{"text": r.text} for r in result.requirements if r.text.strip()]
        used_fallback = False
    except Exception:
        requirements = [{"text": ln.strip()} for ln in jd_text.splitlines()
                        if len(ln.strip()) >= 8]
        used_fallback = True
    return {"requirements": requirements, "jd_text": jd_text, "attempt": 0,
            "company": state.get("company", ""), "role": state.get("role", ""),
            "used_fallback": used_fallback}


def match(state: JobTailorState) -> dict:
    """Find journal evidence for each requirement (embeddings or keywords)."""
    conn = state.get("conn")
    if conn is None:
        return {"matched": [], "evidence": []}
    pool = evidence_pool(conn)
    matched = match_evidence(state.get("requirements", []), pool)
    return {"matched": matched, "evidence": flatten_evidence(matched)}


def write_bullets(state: JobTailorState) -> dict:
    """Draft bullets with the model, or quote top evidence lines as fallback."""
    attempt = state.get("attempt", 0) + 1
    model = state.get("model_name") or MODEL_NAME
    prompt = (PROMPTS_DIR / "bullets.txt").read_text(encoding="utf-8")
    prompt = (prompt
              .replace("{requirements}", _requirements_prompt(state.get("requirements", [])))
              .replace("{evidence}", _evidence_prompt(state.get("evidence", []))))
    fb = _feedback(state)
    if fb:
        prompt += "\n\n" + fb
    try:
        result = chat([{"role": "user", "content": prompt}], model=model,
                      schema=Bullets, temperature=JOURNAL_TEMPERATURE)
        bullets = [{"text": b.text, "cites": b.cites}
                   for b in result.bullets if b.text.strip()]
        return {"bullets": bullets, "attempt": attempt, "used_fallback": False}
    except Exception:
        return {"bullets": fallback_bullets(state), "attempt": attempt,
                "used_fallback": True}


def verify(state: JobTailorState) -> dict:
    """Every bullet must cite evidence lines that support its numbers/URLs."""
    by_id = {e["id"]: {"title": None, "body": e["text"]}
             for e in state.get("evidence", [])}
    return {"bad": verify_bullets(state.get("bullets", []), by_id)}


def save(state: JobTailorState) -> dict:
    """Persist bullets with citations; drop unsupported ones with warnings."""
    bullets = state.get("bullets", [])
    bad = state.get("bad") or {}
    kept = [b for i, b in enumerate(bullets) if i not in bad]
    warnings = []
    for i, reasons in sorted(bad.items()):
        if i < len(bullets):
            warnings.append(
                f"dropped unsupported bullet \"{bullets[i]['text'][:60]}…\": "
                f"{'; '.join(reasons)}"
            )
    if state.get("used_fallback"):
        warnings.append("bullets used the template fallback (model unavailable)")
    if not state.get("evidence"):
        warnings.append("no journal evidence to match against")
    conn = state.get("conn")
    artifact_id = 0
    if conn is not None and state.get("job_id"):
        from ..db import connect  # noqa: F401  (ensure schema helpers load)
        cur = conn.execute(
            "INSERT INTO job_artifact (job_id, kind, body, citations, warnings, "
            "used_fallback) VALUES (?, 'bullets', ?, ?, ?, ?)",
            (state["job_id"],
             "\n".join(f"- {b['text']}" for b in kept),
             json.dumps(kept),
             json.dumps(warnings),
             int(bool(state.get("used_fallback")))),
        )
        conn.commit()
        artifact_id = cur.lastrowid
    return {"artifact_id": artifact_id, "warnings": warnings, "bullets": kept}


def tailor_router(state: JobTailorState) -> Literal["write_bullets", "save"]:
    if state.get("bad") and state.get("attempt", 0) < MAX_ATTEMPTS:
        return "write_bullets"
    return "save"


def build_job_tailor_graph():
    g = StateGraph(JobTailorState)
    for name, fn in [("parse_jd", parse_jd), ("match", match),
                     ("write_bullets", write_bullets), ("verify", verify),
                     ("save", save)]:
        g.add_node(name, fn)
    g.add_edge(START, "parse_jd")
    g.add_edge("parse_jd", "match")
    g.add_edge("match", "write_bullets")
    g.add_edge("write_bullets", "verify")
    g.add_conditional_edges("verify", tailor_router,
                            {"write_bullets": "write_bullets", "save": "save"})
    g.add_edge("save", END)
    return g.compile()


# --- cover letter (#41) ----------------------------------------------------------

def template_cover_letter(state: dict) -> str:
    """Deterministic letter grounded in the same evidence — fact-checked too."""
    company = state.get("company") or "your team"
    role = state.get("role") or "the role"
    evidence = "\n".join(f"- {e['text']}" for e in state.get("evidence", [])[:5])
    requirements = "\n".join(f"- {r['text']}" for r in state.get("requirements", []))
    return (
        f"Dear {company} team,\n\n"
        f"I am applying for the {role} role. Requirements I have worked on:\n"
        f"{requirements or '(see evidence)'}\n\n"
        f"Relevant work from my journal:\n{evidence or '(no evidence yet)'}\n\n"
        "Sincerely,\n"
    )


def draft_cover_letter(
    conn,
    job_id: int,
    *,
    model_name: str | None = None,
    embedder=None,
) -> dict:
    """Cover letter grounded in cited journal lines, fact-checked and stored.

    Reuses parse_jd + match_evidence and the draft fact checker (check_facts):
    every date, time, URL, handle and number in the letter must exist in the
    requirements or the matched evidence. Retries with exact feedback up to
    MAX_ATTEMPTS; a letter that still fails is stored with its warnings.
    """
    job = get_job(conn, job_id)
    if job is None:
        raise ValueError(f"no job #{job_id}")
    state: dict = {
        "conn": conn, "job_id": job_id, "jd_text": job.get("jd_text") or "",
        "company": job["company"], "role": job["role"],
        "model_name": model_name or MODEL_NAME,
    }
    parsed = parse_jd(state)
    state.update(parsed)
    state.update(match(state))
    source = "\n".join([
        state.get("jd_text") or "",
        _requirements_prompt(state.get("requirements", [])),
        "\n".join(e["text"] for e in state.get("evidence", [])),
    ])
    model = state["model_name"]
    prompt_tpl = (PROMPTS_DIR / "cover.txt").read_text(encoding="utf-8")
    used_fallback = False
    warnings: list[str] = []
    letter = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        feedback = ""
        if warnings:
            feedback = ("The previous attempt had problems. Fix them or OMIT "
                        "the claim; never invent facts:\n"
                        + "\n".join(f"- {w}" for w in warnings))
        prompt = (prompt_tpl
                  .replace("{company}", state.get("company") or "")
                  .replace("{role}", state.get("role") or "")
                  .replace("{jd_text}", state.get("jd_text") or "")
                  .replace("{requirements}", _requirements_prompt(state.get("requirements", [])))
                  .replace("{evidence}", _evidence_prompt(state.get("evidence", [])))
                  .replace("{feedback}", feedback))
        try:
            letter = chat([{"role": "user", "content": prompt}], model=model,
                          temperature=JOURNAL_TEMPERATURE)
            if not isinstance(letter, str) or not letter.strip():
                raise ValueError("empty cover letter from model")
            letter = letter.strip()
            used_fallback = False
        except Exception:
            letter = template_cover_letter(state)
            used_fallback = True
        warnings = check_facts(letter, source)
        if not warnings:
            break
    if used_fallback:
        warnings = warnings + ["cover letter used the template fallback (model unavailable)"]
    citations = [e["id"] for e in state.get("evidence", [])]
    cur = conn.execute(
        "INSERT INTO job_artifact (job_id, kind, body, citations, warnings, "
        "used_fallback) VALUES (?, 'cover', ?, ?, ?, ?)",
        (job_id, letter, json.dumps(citations), json.dumps(warnings),
         int(bool(used_fallback))),
    )
    conn.commit()
    return {"artifact_id": cur.lastrowid, "letter": letter,
            "citations": citations, "warnings": warnings,
            "used_fallback": used_fallback, "requirements": state.get("requirements", [])}
