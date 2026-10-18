"""Draft graph: gather -> voice -> write -> fact_check -> rules_check -> save.

M0: stubbed end to end with deterministic nodes (no LLM). M4 replaces `write`
with the draft prompt + retry feedback and wires verify.check_facts /
check_rules into the conditional retry loop (docs/PLAN.md section 8).
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


class DraftState(TypedDict, total=False):
    workspace_id: int
    source_kind: Literal["journal", "post", "idea", "freeform"]
    source_ids: list[int]
    brief: str                           # optional: "announce the workshop on 4 Nov"
    model_name: str
    source_text: str                     # the ONLY facts the draft may use
    voice_examples: list[str]
    rules: dict
    draft: str
    violations: list[str]
    attempt: int
    used_fallback: bool
    post_id: int
    warnings: Annotated[list[str], operator.add]


# --- stub nodes -------------------------------------------------------------

def gather(state: DraftState) -> dict:
    return {"source_text": state.get("brief", ""), "attempt": 0}


def voice(state: DraftState) -> dict:
    return {"voice_examples": []}


def write(state: DraftState) -> dict:
    """Stub: fixed template filled from facts. M4 uses prompts/draft.txt."""
    body = state.get("source_text", "").strip() or "(no source facts yet)"
    return {"draft": f"[TEMPLATE DRAFT]\n\n{body}", "used_fallback": True,
            "attempt": state.get("attempt", 0) + 1}


def fact_check(state: DraftState) -> dict:
    """Stub: passes. M4 runs verify.check_facts(draft, source_text)."""
    return {}


def rules_check(state: DraftState) -> dict:
    """Stub: passes. M4 runs verify.check_rules(draft, rules)."""
    return {}


def save(state: DraftState) -> dict:
    """Stub: no DB write yet (M4 stores the post with warnings)."""
    return {"post_id": 0}


def draft_router(state: DraftState) -> Literal["write", "save"]:
    from ..config import MAX_ATTEMPTS

    if not state.get("violations"):
        return "save"
    if state.get("attempt", 0) >= MAX_ATTEMPTS:
        return "save"                    # saved with warnings so the human sees them
    return "write"


def build_draft_graph():
    g = StateGraph(DraftState)
    for name, fn in [("gather", gather), ("voice", voice), ("write", write),
                     ("fact_check", fact_check), ("rules_check", rules_check),
                     ("save", save)]:
        g.add_node(name, fn)
    g.add_edge(START, "gather")
    g.add_edge("gather", "voice")
    g.add_edge("voice", "write")
    g.add_edge("write", "fact_check")
    g.add_edge("fact_check", "rules_check")
    g.add_conditional_edges("rules_check", draft_router, {"write": "write", "save": "save"})
    g.add_edge("save", END)
    return g.compile()
