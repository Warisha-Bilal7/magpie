"""Planner: nudges, post status flow, reminders, calendar export.

Everything here is deterministic — no model calls. Nudge text is a template;
the optional "drafts ready" suggestion just lists draft posts (running the
draft graph on them is a human decision). See docs/PLAN.md section 7.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone

POST_STATUSES = ("idea", "draft", "approved", "scheduled", "published")

# Allowed status transitions. Published is terminal; anything can go back to
# draft via the editor, but nothing skips the approved gate to scheduled.
TRANSITIONS: dict[str, set[str]] = {
    "idea": {"draft"},
    "draft": {"approved"},
    "approved": {"draft", "scheduled"},
    "scheduled": {"approved", "published"},
    "published": set(),
}


# --- nudges (#32, #36) ------------------------------------------------------

def due_nudges(workspaces: list[dict], last_post: dict[int, date],
               today: date) -> list[dict]:
    """Workspaces that have gone quiet for longer than their cadence target."""
    out = []
    for w in workspaces:
        if not w.get("cadence_days"):
            continue
        last = last_post.get(w["id"])
        gap = (today - last).days if last else None
        if gap is None or gap >= w["cadence_days"]:
            out.append({"workspace": w["name"], "days_since": gap,
                        "overdue_by": None if gap is None else gap - w["cadence_days"],
                        "cadence_days": w["cadence_days"]})
    return out


def nudge_text(nudge: dict) -> str:
    """Template: "9 days since your last Substack post (2 days over your cadence)." """
    name = nudge["workspace"]
    if nudge.get("days_since") is None:
        cadence = nudge.get("cadence_days")
        if cadence:
            return f"No {name} post yet — your cadence is every {cadence} days."
        return f"No {name} post yet."
    text = f"{nudge['days_since']} days since your last {name} post"
    if nudge.get("overdue_by"):
        text += f" ({nudge['overdue_by']} days over your cadence)"
    return text + "."


def drafts_ready(posts: list[dict], workspace_id: int | None = None) -> list[dict]:
    """Draft posts waiting for a human — the 'here are drafts from this week' hint."""
    out = [p for p in posts if p.get("status") == "draft"]
    if workspace_id is not None:
        out = [p for p in out if p.get("workspace_id") == workspace_id]
    return out


# --- post status flow (#31) -------------------------------------------------

def set_post_status(
    conn: sqlite3.Connection,
    post_id: int,
    status: str,
    *,
    scheduled_at: str | None = None,
    published_at: str | None = None,
) -> dict:
    """Move a post through draft -> approved -> scheduled/published.

    Validates the transition; scheduling requires a time. Raises ValueError
    with the current and requested status so the CLI can print something real.
    """
    from .db import get_post

    if status not in POST_STATUSES:
        raise ValueError(f"unknown status '{status}' (pick from {POST_STATUSES})")
    post = get_post(conn, post_id)
    if post is None:
        raise ValueError(f"no post #{post_id}")
    current = post["status"]
    if status != current and status not in TRANSITIONS.get(current, set()):
        raise ValueError(f"cannot move post #{post_id} from '{current}' to '{status}'")
    if status == "scheduled" and not scheduled_at:
        raise ValueError("scheduling needs a time (--at ...)")
    sets, params = ["status = ?"], [status]
    if scheduled_at is not None:
        sets.append("scheduled_at = ?")
        params.append(scheduled_at)
    if published_at is not None:
        sets.append("published_at = ?")
        params.append(published_at)
    params.append(post_id)
    conn.execute(f"UPDATE post SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return get_post(conn, post_id)


# --- reminders (#33) --------------------------------------------------------

def add_reminder(
    conn: sqlite3.Connection,
    kind: str,                          # post | deadline | follow_up | review
    *,
    title: str,
    due_at: str,
    ref_table: str | None = None,
    ref_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO reminder (kind, ref_table, ref_id, title, due_at) VALUES (?, ?, ?, ?, ?)",
        (kind, ref_table, ref_id, title, due_at),
    )
    conn.commit()
    return cur.lastrowid


def list_reminders(conn: sqlite3.Connection, include_done: bool = False) -> list[dict]:
    q = "SELECT * FROM reminder"
    if not include_done:
        q += " WHERE done = 0"
    rows = conn.execute(q + " ORDER BY due_at").fetchall()
    return [dict(r) for r in rows]


def complete_reminder(conn: sqlite3.Connection, reminder_id: int) -> None:
    conn.execute("UPDATE reminder SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()


# --- calendar export (#35) --------------------------------------------------

def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(events: list[dict]) -> str:
    """events: [{"uid": str, "title": str, "start": aware datetime, "minutes": int}]"""
    now = datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//content-desk//EN"]
    for e in events:
        end = e["start"] + timedelta(minutes=e.get("minutes", 30))
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}@content-desk", f"DTSTAMP:{_fmt(now)}",
                  f"DTSTART:{_fmt(e['start'])}", f"DTEND:{_fmt(end)}",
                  f"SUMMARY:{_esc(e['title'])}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def scheduled_events(posts: list[dict]) -> list[dict]:
    """Scheduled posts as calendar events (skips rows without a valid time)."""
    events = []
    for p in posts:
        raw = p.get("scheduled_at")
        if not raw:
            continue
        try:
            start = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        events.append({
            "uid": str(p["id"]),
            "title": p.get("title") or f"Draft #{p['id']}",
            "start": start,
            "minutes": 30,
        })
    return events


def last_published_dates(conn: sqlite3.Connection) -> dict[int, date]:
    """Most recent published date per workspace (for due_nudges)."""
    rows = conn.execute(
        """SELECT workspace_id, MAX(COALESCE(published_at, '')) AS last
           FROM post WHERE status = 'published'
           GROUP BY workspace_id"""
    ).fetchall()
    out: dict[int, date] = {}
    for r in rows:
        raw = (r["last"] or "")[:10]
        try:
            out[r["workspace_id"]] = date.fromisoformat(raw)
        except ValueError:
            continue
    return out
