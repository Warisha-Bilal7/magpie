"""Context pack generator (F8, issue #42).

Assembles a paste-ready markdown brief for one project: recent approved
journal lines (with dates), decisions, open questions and linked idea cards.
Deterministic — no model needed, so it works offline and its output is
reproducible. Captures are selected by `project_id` or by a tag matching the
project name; journal lines and ideas are linked back through the capture ids
they cite.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from .db import captures_for_project

# Heuristics for decision and question lines inside journal text.
_DECISION_RE = re.compile(
    r"\b(decid(?:ed|e|ing)|chose|choosing|going with|settled on|opted for|"
    r"picked|selected)\b", re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"\?\s*$")

DEFAULT_DAYS = 14


def _parse_ids(raw) -> list[int]:
    """journal_line.capture_ids and idea.source_ids are stored as JSON."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw]
    try:
        return [int(x) for x in json.loads(raw)]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _is_decision(text: str) -> bool:
    return bool(_DECISION_RE.search(text))


def _is_question(text: str) -> bool:
    return bool(_QUESTION_RE.search(text.strip()))


def project_capture_ids(conn, project_name: str) -> list[int]:
    """Capture ids belonging to a project, matched by project_id or tag."""
    row = conn.execute(
        "SELECT id FROM project WHERE name = ?", (project_name,)
    ).fetchone()
    ids: list[int] = []
    if row is not None:
        ids.extend(c["id"] for c in captures_for_project(conn, row["id"]))
    tag_rows = conn.execute(
        "SELECT id FROM capture WHERE tags LIKE ? ORDER BY id DESC LIMIT 500",
        (f"%{project_name}%",),
    ).fetchall()
    ids.extend(r["id"] for r in tag_rows)
    # de-dupe, keep insertion order (newest capture ids last from tag query)
    seen: set[int] = set()
    out: list[int] = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def project_journal_lines(conn, project_name: str, days: int = DEFAULT_DAYS) -> list[dict]:
    """Approved journal lines whose captures belong to the project.

    Returns [{"id", "text", "day", "capture_ids"}], newest day first.
    """
    cap_ids = project_capture_ids(conn, project_name)
    if not cap_ids:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = conn.execute(
        """SELECT jl.id, jl.text, jl.capture_ids, je.day
           FROM journal_line jl
           JOIN journal_entry je ON je.id = jl.entry_id
           WHERE je.status = 'approved' AND je.day >= ?
           ORDER BY je.day DESC, jl.id DESC""",
        (cutoff,),
    ).fetchall()
    cap_set = set(cap_ids)
    out = []
    for r in rows:
        cited = set(_parse_ids(r["capture_ids"]))
        if cited & cap_set:
            out.append({"id": r["id"], "text": r["text"], "day": r["day"],
                        "capture_ids": sorted(cited)})
    return out


def linked_ideas(conn, project_name: str) -> list[dict]:
    """Idea cards whose source captures belong to the project."""
    cap_set = set(project_capture_ids(conn, project_name))
    if not cap_set:
        return []
    rows = conn.execute(
        "SELECT * FROM idea ORDER BY status, id"
    ).fetchall()
    out = []
    for r in rows:
        source_ids = set(_parse_ids(r["source_ids"]))
        if source_ids & cap_set:
            out.append({"id": r["id"], "title": r["title"], "status": r["status"],
                        "next_step": r["next_step"]})
    return out


def context_pack(conn, project_name: str, days: int = DEFAULT_DAYS) -> str:
    """Markdown brief: journal lines, decisions, open questions, idea cards.

    Paste this at the top of a new chat in any AI account so scattered
    conversations share the same project context.
    """
    lines = project_journal_lines(conn, project_name, days=days)
    ideas = linked_ideas(conn, project_name)

    decisions = [ln for ln in lines if _is_decision(ln["text"])]
    questions = [ln for ln in lines if _is_question(ln["text"])]
    seen: set[int] = set()
    unique_decisions = []
    for d in decisions:
        if d["id"] not in seen:
            seen.add(d["id"])
            unique_decisions.append(d)
    seen = set()
    unique_questions = []
    for q in questions:
        if q["id"] not in seen:
            seen.add(q["id"])
            unique_questions.append(q)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = [f"# Project brief: {project_name}", "",
          f"Generated {now}, last {days} days, {len(lines)} journal lines.",
          "", "## Recent journal lines", ""]
    if lines:
        for ln in lines:
            md.append(f"- ({ln['day']}) {ln['text']}")
    else:
        md.append("_(no approved journal lines matched this project yet)_")

    md += ["", "## Decisions", ""]
    if unique_decisions:
        for d in unique_decisions:
            md.append(f"- ({d['day']}) {d['text']}")
    else:
        md.append("_(none recorded in this window)_")

    md += ["", "## Open questions", ""]
    if unique_questions:
        for q in unique_questions:
            md.append(f"- ({q['day']}) {q['text']}")
    else:
        md.append("_(none recorded in this window)_")

    md += ["", "## Linked ideas", ""]
    if ideas:
        for idea in ideas:
            step = f" — next: {idea['next_step']}" if idea.get("next_step") else ""
            md.append(f"- [{idea['status']}] {idea['title']}{step}")
    else:
        md.append("_(no idea cards linked to this project's captures)_")

    return "\n".join(md) + "\n"
