"""Journal graph: select -> summarize -> verify -> store. See docs/PLAN.md section 3.

The model writes lines with citations; deterministic code verifies every line
against the captures it cites. Lines that stay unsupported after
MAX_ATTEMPTS retries are dropped with a warning — the journal never invents.
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..config import JOURNAL_TEMPERATURE, MAX_ATTEMPTS, MODEL_NAME, PROMPTS_DIR
from ..llm import chat
from ..verify import unsupported_reasons

TRIM_CHARS = 1200  # per-capture body budget so a day fits the prompt


class JournalLine(BaseModel):            # structured output from the model
    text: str
    cites: list[int]                     # capture ids


class JournalLines(BaseModel):
    lines: list[JournalLine]


class JournalState(TypedDict, total=False):
    day: str                             # yyyy-mm-dd
    kind: str                            # daily | weekly
    model_name: str
    captures: list[dict]                 # FULL captures (verify checks these)
    trimmed: list[dict]                  # trimmed copies for the prompt only
    source_lines: list[dict]             # weekly mode: daily lines {text, capture_ids, day}
    lines: list[dict]                    # {"text", "cites"}
    bad: dict[int, list[str]]            # line index -> reasons
    attempt: int
    entry_id: int
    conn: object                         # sqlite connection for store (local use)
    used_fallback: bool
    warnings: Annotated[list[str], operator.add]


# --- deterministic pieces (no model) ---------------------------------------

def fallback_digest(state: JournalState) -> list[dict]:
    """Baseline when the model is off: one cited line per capture (daily),
    or one per day quoting that day's verified lines (weekly).

    Line text never adds ids or dates the source lacks — the verifier
    would (rightly) drop them as invented numbers.
    """
    if state.get("source_lines") is not None:
        by_day: dict[str, list[dict]] = {}
        for ln in state["source_lines"]:
            by_day.setdefault(ln.get("day", ""), []).append(ln)
        lines = []
        for day in sorted(by_day):
            day_lines = by_day[day]
            text = " | ".join(l["text"] for l in day_lines)
            cites = sorted({c for l in day_lines for c in l.get("capture_ids", [])})
            lines.append({"text": text, "cites": cites})
        return lines
    def _digest_text(c: dict) -> str:
        if c.get("title"):
            return c["title"]
        first = (c.get("body") or "").strip().splitlines()
        if first:
            return first[0][:80]
        return c.get("origin") or "capture"

    return [{"text": _digest_text(c), "cites": [c["id"]]} for c in state.get("captures", [])]


def _prompt_captures(trimmed: list[dict]) -> str:
    return "\n\n".join(
        f"[capture {c['id']}] ({c.get('origin') or 'unknown'}) {c.get('title') or ''}\n{c['body']}"
        for c in trimmed
    )


def _prompt_source_lines(source_lines: list[dict]) -> str:
    return "\n".join(
        f"[{l['day']}] (captures {l['capture_ids']}) {l['text']}" for l in source_lines
    )


def _feedback(state: JournalState) -> str:
    bad = state.get("bad") or {}
    if not bad:
        return ""
    lines = state.get("lines", [])
    rows = []
    for i, reasons in bad.items():
        if i < len(lines):
            rows.append(f"- \"{lines[i]['text']}\" -> {'; '.join(reasons)}")
    if not rows:
        return ""
    return ("The previous attempt had problems. Fix the facts or OMIT the line; "
            "never invent numbers or links:\n" + "\n".join(rows))


# --- graph nodes ------------------------------------------------------------

def select(state: JournalState) -> dict:
    """Keep full captures for verify; make trimmed copies for the prompt."""
    trimmed = []
    for c in state.get("captures", []):
        t = dict(c)
        if len(t.get("body") or "") > TRIM_CHARS:
            t["body"] = t["body"][:TRIM_CHARS] + " …[trimmed]"
        trimmed.append(t)
    return {"trimmed": trimmed, "attempt": 0}


def summarize(state: JournalState) -> dict:
    """One concrete item per line, structured output; digest fallback if the model fails."""
    attempt = state.get("attempt", 0) + 1
    model = state.get("model_name") or MODEL_NAME
    source_lines = state.get("source_lines")
    if source_lines is not None:
        material = _prompt_source_lines(source_lines)
        kind_note = "summarize these daily journal lines into a weekly digest"
    else:
        material = _prompt_captures(state.get("trimmed", []))
        kind_note = "summarize these captures into a journal"
    # replace, not format(): the prompt contains JSON braces
    prompt = (PROMPTS_DIR / "journal.txt").read_text(encoding="utf-8").replace("{captures}", material)
    prompt = prompt.replace("summarizing a person's captured work notes into a journal.",
                            kind_note + ".")
    fb = _feedback(state)
    if fb:
        prompt += "\n\n" + fb
    try:
        result = chat(
            [{"role": "user", "content": prompt}],
            model=model,
            schema=JournalLines,
            temperature=JOURNAL_TEMPERATURE,
        )
        lines = [{"text": ln.text, "cites": ln.cites} for ln in result.lines]
        return {"lines": lines, "attempt": attempt, "used_fallback": False}
    except Exception:  # model unreachable or errored — always produce something
        lines = fallback_digest(state)
        return {"lines": lines, "attempt": attempt, "used_fallback": True}


def verify(state: JournalState) -> dict:
    """Every line must cite captures that support its numbers and URLs."""
    by_id = {c["id"]: c for c in state.get("captures", [])}
    bad: dict[int, list[str]] = {}
    for i, ln in enumerate(state.get("lines", [])):
        reasons = unsupported_reasons(ln, by_id)
        if reasons:
            bad[i] = reasons
    return {"bad": bad}


def store(state: JournalState) -> dict:
    """Drop persistent bad lines with warnings; persist the rest."""
    bad = state.get("bad") or {}
    lines = state.get("lines", [])
    kept = [ln for i, ln in enumerate(lines) if i not in bad]
    warnings = []
    for i, reasons in sorted(bad.items()):
        if i < len(lines):
            snippet = lines[i]["text"][:60]
            warnings.append(f"dropped unsupported line \"{snippet}…\": {'; '.join(reasons)}")
    if not state.get("captures") and not state.get("source_lines"):
        warnings.append(f"no captures for {state.get('day', '?')}")
    conn = state.get("conn")
    entry_id = 0
    if conn is not None:
        from ..db import store_journal_entry
        entry_id = store_journal_entry(
            conn, state.get("day", ""), state.get("kind", "daily"), kept
        )
    return {"entry_id": entry_id, "lines": kept, "warnings": warnings}


def journal_router(state: JournalState) -> Literal["summarize", "store"]:
    if state.get("bad") and state.get("attempt", 0) < MAX_ATTEMPTS:
        return "summarize"
    return "store"


def build_journal_graph():
    g = StateGraph(JournalState)
    for name, fn in [("select", select), ("summarize", summarize),
                     ("verify", verify), ("store", store)]:
        g.add_node(name, fn)
    g.add_edge(START, "select")
    g.add_edge("select", "summarize")
    g.add_edge("summarize", "verify")
    g.add_conditional_edges("verify", journal_router, {"summarize": "summarize", "store": "store"})
    g.add_edge("store", END)
    return g.compile()
