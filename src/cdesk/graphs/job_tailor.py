"""Job tailor graph: parse_jd -> match_evidence -> write_bullets -> verify -> store.

M0: stubbed end to end with deterministic nodes (no LLM). M6 replaces
`parse_jd` and `write_bullets` with structured-output LLM calls and reuses
verify.unsupported_reasons for the citation check (docs/PLAN.md section 3).
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel


class JDRequirement(BaseModel):
    text: str


class JDRequirements(BaseModel):
    requirements: list[JDRequirement]


class Bullet(BaseModel):
    text: str
    cites: list[int]                     # journal line ids


class Bullets(BaseModel):
    bullets: list[Bullet]


class JobTailorState(TypedDict, total=False):
    job_id: int
    jd_text: str
    requirements: list[dict]             # {"text", "line_ids"}
    bullets: list[dict]                  # {"text", "cites"}
    model_name: str
    attempt: int
    used_fallback: bool
    warnings: Annotated[list[str], operator.add]


def parse_jd(state: JobTailorState) -> dict:
    """Stub: split the JD into non-empty lines. M6 uses structured output."""
    lines = [ln.strip() for ln in state.get("jd_text", "").splitlines() if ln.strip()]
    return {"requirements": [{"text": ln, "line_ids": []} for ln in lines],
            "used_fallback": True}


def match_evidence(state: JobTailorState) -> dict:
    """Stub: no evidence matching yet (M6 uses embeddings)."""
    return {}


def write_bullets(state: JobTailorState) -> dict:
    """Stub: echo requirements as bullets. M6 uses prompts/bullets.txt."""
    bullets = [{"text": f"- {r['text']}", "cites": []}
               for r in state.get("requirements", [])]
    return {"bullets": bullets}


def verify(state: JobTailorState) -> dict:
    """Stub: warn on bullets without citations. M6 uses verify.unsupported_reasons."""
    bad = sum(1 for b in state.get("bullets", []) if not b.get("cites"))
    warn = [f"stub verify: {bad} bullet(s) have no citations"] if bad else []
    return {"warnings": warn}


def store(state: JobTailorState) -> dict:
    """Stub: no DB write yet (M6 stores bullets on the job)."""
    return {}


def build_job_tailor_graph():
    g = StateGraph(JobTailorState)
    for name, fn in [("parse_jd", parse_jd), ("match_evidence", match_evidence),
                     ("write_bullets", write_bullets), ("verify", verify),
                     ("store", store)]:
        g.add_node(name, fn)
    g.add_edge(START, "parse_jd")
    g.add_edge("parse_jd", "match_evidence")
    g.add_edge("match_evidence", "write_bullets")
    g.add_edge("write_bullets", "verify")
    g.add_edge("verify", "store")
    g.add_edge("store", END)
    return g.compile()
