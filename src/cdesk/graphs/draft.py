"""Draft graph: gather -> voice -> write -> fact_check -> rules_check -> save.

The model drafts; deterministic code checks every date, time, URL, handle and
number against the source, plus the workspace platform rules. Violations are
fed back verbatim for up to MAX_ATTEMPTS retries; a draft that still fails is
saved with its warnings so the human sees them (docs/PLAN.md section 8).
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import DRAFT_TEMPERATURE, MAX_ATTEMPTS, MODEL_NAME, PROMPTS_DIR
from ..llm import chat
from ..verify import check_facts, check_rules
from ..voice import voice_examples


class DraftState(TypedDict, total=False):
    workspace_id: int
    source_kind: Literal["journal", "post", "idea", "freeform"]
    source_ids: list[int]
    brief: str                           # optional: "announce the workshop on 4 Nov"
    model_name: str
    source_text: str                     # the ONLY facts the draft may use
    voice_examples: list[str]
    rules: dict
    platform: str                        # workspace kind, drives the prompt
    draft: str
    violations: list[str]
    attempt: int
    used_fallback: bool
    post_id: int
    parent_post_id: int                  # set when repurposing
    conn: object                         # sqlite connection (local use)
    warnings: Annotated[list[str], operator.add]


# --- deterministic pieces (no model) ----------------------------------------

def _feedback(state: DraftState) -> str:
    violations = state.get("violations") or []
    if not violations:
        return ""
    rows = "\n".join(f"- {v}" for v in violations)
    return ("The previous attempt had problems. Fix them or OMIT the claim; "
            "never invent facts:\n" + rows)


def template_fallback(state: DraftState) -> str:
    """Baseline when the model is off. Uses ONLY source facts — the fact
    checker runs on this too, and it must not trip on the template itself."""
    body = (state.get("source_text") or "").strip() or "(no source facts)"
    platform = state.get("platform") or "social"
    return f"[TEMPLATE DRAFT - {platform}]\n\n{body}"


# --- graph nodes ------------------------------------------------------------

def gather(state: DraftState) -> dict:
    """Assemble the allowed facts (journal lines, post, idea or brief) and
    the workspace rules/platform the draft must obey."""
    conn = state.get("conn")
    ws_id = state.get("workspace_id")
    rules = state.get("rules")
    platform = state.get("platform")
    if conn is not None and ws_id is not None:
        from ..workspaces import effective_rules, get_workspace
        ws = get_workspace(conn, ws_id)
        if ws is not None:
            if rules is None:
                rules = effective_rules(ws)
            if not platform:
                platform = ws["kind"]
    kind = state.get("source_kind") or "freeform"
    ids = state.get("source_ids") or []
    parts: list[str] = []
    if conn is not None and ids:
        if kind == "journal":
            from ..db import entry_lines
            parts = [ln["text"] for i in ids for ln in entry_lines(conn, i)]
        elif kind == "post":
            from ..db import get_post
            parts = [(get_post(conn, i) or {}).get("body_md") or "" for i in ids]
        elif kind == "idea":
            from ..db import get_idea
            for i in ids:
                idea = get_idea(conn, i)
                if idea:
                    parts.append(idea.get("title") or "")
                    parts.append(idea.get("note") or "")
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        text = (state.get("source_text") or "").strip()
    if not text:
        text = (state.get("brief") or "").strip()
    return {"source_text": text, "rules": rules or {},
            "platform": platform or "social", "attempt": 0}


def voice(state: DraftState) -> dict:
    """Top-3 similar past posts as style examples; empty list if unavailable."""
    conn = state.get("conn")
    ws_id = state.get("workspace_id")
    if conn is None or ws_id is None:
        return {"voice_examples": []}
    try:
        query = (state.get("brief") or state.get("source_text") or "")[:200]
        examples = voice_examples(conn, ws_id, query, k=3)
        return {"voice_examples": [ex["body"] for ex in examples]}
    except Exception:  # Ollama down or no corpus — drafting must still work
        return {"voice_examples": []}


def write(state: DraftState) -> dict:
    """Draft with the model, or fall back to the template. Attempt increments
    here so the router sees it after the check nodes."""
    attempt = state.get("attempt", 0) + 1
    model = state.get("model_name") or MODEL_NAME
    rules = state.get("rules") or {}
    rules_str = ", ".join(f"{k}={v}" for k, v in rules.items())
    examples = state.get("voice_examples") or []
    examples_str = "\n---\n".join(examples) if examples else "(none)"
    # replace, not format(): the prompt contains JSON braces
    prompt = (PROMPTS_DIR / "draft.txt").read_text(encoding="utf-8")
    prompt = (prompt
              .replace("{platform}", state.get("platform") or "social")
              .replace("{rules}", rules_str)
              .replace("{feedback}", _feedback(state))
              .replace("{voice_examples}", examples_str)
              .replace("{source_text}", state.get("source_text", ""))
              .replace("{brief}", (state.get("brief") or "(none)")))
    try:
        draft = chat(
            [{"role": "user", "content": prompt}],
            model=model,
            temperature=DRAFT_TEMPERATURE,
        )
        if not isinstance(draft, str) or not draft.strip():
            raise ValueError("empty draft from model")
        return {"draft": draft.strip(), "attempt": attempt, "used_fallback": False}
    except Exception:  # model unreachable or errored — always produce something
        return {"draft": template_fallback(state), "attempt": attempt,
                "used_fallback": True}


def fact_check(state: DraftState) -> dict:
    """Every date, time, URL, handle and number must exist in the source."""
    return {"violations": check_facts(state.get("draft", ""),
                                      state.get("source_text", ""))}


def rules_check(state: DraftState) -> dict:
    """Length, hashtags and banned phrases; keeps the fact violations too."""
    prior = state.get("violations") or []
    return {"violations": prior + check_rules(state.get("draft", ""),
                                              state.get("rules") or {})}


def save(state: DraftState) -> dict:
    """Persist the draft with its leftover warnings so the human sees them."""
    violations = list(state.get("violations") or [])
    warnings = violations
    if state.get("used_fallback"):
        warnings = warnings + ["draft used the template fallback (model unavailable)"]
    conn = state.get("conn")
    post_id = 0
    if conn is not None:
        from ..db import store_post
        post_id = store_post(
            conn,
            state.get("workspace_id", 0),
            state.get("draft", ""),
            status="draft",
            source_ids={"kind": state.get("source_kind"),
                        "ids": state.get("source_ids") or []},
            parent_post_id=state.get("parent_post_id"),
            warnings=warnings,
        )
    return {"post_id": post_id, "warnings": warnings}


def draft_router(state: DraftState) -> Literal["write", "save"]:
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


def repurpose_post(conn, post_id: int, workspace_id: int) -> dict:
    """One post, several channels: re-draft an existing post's facts into
    another workspace's voice and rules (child post links to the parent)."""
    from ..db import get_post
    if get_post(conn, post_id) is None:
        raise ValueError(f"no post #{post_id}")
    return build_draft_graph().invoke({
        "conn": conn,
        "workspace_id": workspace_id,
        "source_kind": "post",
        "source_ids": [post_id],
        "brief": "Repurpose this post for the new channel.",
        "parent_post_id": post_id,
    })
