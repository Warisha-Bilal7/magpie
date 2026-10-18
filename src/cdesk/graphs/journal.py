"""Journal graph: select -> summarize -> verify -> store. See docs/PLAN.md section 3.

M0: stubbed end to end with deterministic nodes (no LLM). M2 replaces
`summarize` with structured-output LLM calls and wires verify.py's
`unsupported_reasons` into the verify/retry loop.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel


class JournalLine(BaseModel):            # structured output from the model
    text: str
    cites: list[int]                     # capture ids


class JournalLines(BaseModel):
    lines: list[JournalLine]


class JournalState(TypedDict, total=False):
    day: str                             # yyyy-mm-dd
    kind: str                            # daily | weekly
    model_name: str
    captures: list[dict]                 # id, origin, title, body (trimmed), happened_at
    lines: list[dict]                    # {"text", "cites"}
    bad: dict[int, list[str]]            # line index -> reasons
    attempt: int
    entry_id: int
    used_fallback: bool
    warnings: Annotated[list[str], operator.add]


# --- stub nodes (deterministic; M2 replaces summarize with the LLM) ---------

def select(state: JournalState) -> dict:
    return {}


def summarize(state: JournalState) -> dict:
    """Stub: one line per capture, citing it. Real version uses the LLM."""
    lines = [
        {"text": (c.get("title") or c.get("origin") or "capture") + f" (#{c['id']})",
         "cites": [c["id"]]}
        for c in state.get("captures", [])
    ]
    return {"lines": lines, "used_fallback": True}


def verify(state: JournalState) -> dict:
    """Stub: drop lines with no cites. M2 uses verify.unsupported_reasons."""
    kept = [ln for ln in state.get("lines", []) if ln.get("cites")]
    dropped = len(state.get("lines", [])) - len(kept)
    warn = [f"stub verify dropped {dropped} line(s) without citations"] if dropped else []
    return {"lines": kept, "warnings": warn}


def store(state: JournalState) -> dict:
    """Stub: no DB write yet (M2 stores entry + lines)."""
    return {"entry_id": 0}


def build_journal_graph():
    g = StateGraph(JournalState)
    for name, fn in [("select", select), ("summarize", summarize),
                     ("verify", verify), ("store", store)]:
        g.add_node(name, fn)
    g.add_edge(START, "select")
    g.add_edge("select", "summarize")
    g.add_edge("summarize", "verify")
    g.add_edge("verify", "store")
    g.add_edge("store", END)
    return g.compile()
