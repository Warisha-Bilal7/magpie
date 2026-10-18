"""Job kanban, deadlines and follow-up nudges (M6 #39).

One row per application. The board groups jobs by status; deadlines sort
inside each column; follow-ups are deterministic date math with no model —
see docs/PLAN.md F9.
"""

import sqlite3
from datetime import date

STATUSES = ("saved", "applied", "interviewing", "offer", "closed")

# Allowed status moves. Closed is terminal; a saved job that was sent becomes
# applied (setting applied_on), and interviewing is the only route to offer.
TRANSITIONS: dict[str, set[str]] = {
    "saved": {"applied", "closed"},
    "applied": {"interviewing", "closed", "saved"},
    "interviewing": {"offer", "closed", "applied"},
    "offer": {"closed", "interviewing"},
    "closed": set(),
}

# A job sitting in "applied" this many days without an interview deserves a
# follow-up nudge.
FOLLOW_UP_DAYS = 7


# --- deterministic nudges (#39) ----------------------------------------------

def due_follow_ups(
    jobs: list[dict], today: date, days: int = FOLLOW_UP_DAYS
) -> list[dict]:
    """Applied jobs with no interview after `days` days — nudged to follow up.

    A job already interviewing/offered/closed, or one whose applied_on is
    missing or unreadable, is never nudged. Best (most overdue) first.
    """
    out = []
    for j in jobs:
        if j.get("status") != "applied":
            continue
        raw = j.get("applied_on")
        if not raw:
            continue
        try:
            applied = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        gap = (today - applied).days
        if gap >= days:
            out.append({**j, "days_since_applied": gap, "overdue_by": gap - days})
    return sorted(out, key=lambda j: -j["days_since_applied"])


def deadline_text(job: dict, today: date) -> str | None:
    """Human line for an approaching/passed deadline, or None when no deadline."""
    raw = job.get("deadline")
    if not raw:
        return None
    try:
        due = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
    gap = (due - today).days
    name = f"{job.get('company', '?')} — {job.get('role', '?')}"
    if gap < 0:
        return f"{name}: deadline passed {-gap} day(s) ago ({due})"
    if gap == 0:
        return f"{name}: deadline is today ({due})"
    return f"{name}: deadline in {gap} day(s) ({due})"


def upcoming_deadlines(
    jobs: list[dict], today: date, within_days: int = 14
) -> list[dict]:
    """Jobs with a deadline inside the window (including overdue), soonest first."""
    out = []
    for j in jobs:
        if not j.get("deadline"):
            continue
        try:
            due = date.fromisoformat(str(j["deadline"])[:10])
        except ValueError:
            continue
        gap = (due - today).days
        if gap <= within_days:
            out.append({**j, "days_to_deadline": gap})
    return sorted(out, key=lambda j: j["days_to_deadline"])


# --- CRUD and board (#39) -----------------------------------------------------

def add_job(
    conn: sqlite3.Connection,
    company: str,
    role: str,
    *,
    url: str | None = None,
    status: str = "saved",
    deadline: str | None = None,
    applied_on: str | None = None,
    jd_text: str | None = None,
    notes: str | None = None,
) -> dict:
    if not company.strip() or not role.strip():
        raise ValueError("company and role are required")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    cur = conn.execute(
        "INSERT INTO job (company, role, url, status, deadline, applied_on, "
        "jd_text, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (company.strip(), role.strip(), url, status, deadline,
         applied_on, jd_text, notes),
    )
    conn.commit()
    return get_job(conn, cur.lastrowid)


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    q, params = "SELECT * FROM job", []
    if status is not None:
        q += " WHERE status = ?"
        params.append(status)
    rows = conn.execute(q + " ORDER BY id DESC", params).fetchall()
    return [dict(r) for r in rows]


def update_job(conn: sqlite3.Connection, job_id: int, **fields) -> dict:
    allowed = {"company", "role", "url", "status", "deadline", "applied_on",
               "jd_text", "notes"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}")
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE job SET {sets} WHERE id = ?", [*fields.values(), job_id])
        conn.commit()
    return get_job(conn, job_id)


def set_job_status(
    conn: sqlite3.Connection, job_id: int, status: str, *, applied_on: str | None = None
) -> dict:
    """Move a job through the kanban with validated transitions.

    Moving to 'applied' stamps applied_on (today unless given) so the
    follow-up nudge can count days since the application went out.
    """
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    job = get_job(conn, job_id)
    if job is None:
        raise ValueError(f"no job #{job_id}")
    current = job["status"]
    if status != current and status not in TRANSITIONS.get(current, set()):
        raise ValueError(f"cannot move job #{job_id} from '{current}' to '{status}'")
    sets, params = ["status = ?"], [status]
    if status == "applied":
        sets.append("applied_on = ?")
        params.append(applied_on or date.today().isoformat())
    params.append(job_id)
    conn.execute(f"UPDATE job SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    return get_job(conn, job_id)


def delete_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("DELETE FROM job WHERE id = ?", (job_id,))
    conn.commit()


def kanban(conn: sqlite3.Connection, today: date | None = None) -> dict[str, list[dict]]:
    """Columns by status (order of STATUSES), each sorted by deadline
    (soonest first, no-deadline last) — the board view."""
    today = today or date.today()
    board: dict[str, list[dict]] = {s: [] for s in STATUSES}
    for job in list_jobs(conn):
        board[job["status"]].append(job)

    def key(j: dict):
        raw = j.get("deadline")
        try:
            return (0, date.fromisoformat(str(raw)[:10])) if raw else (1, date.max)
        except ValueError:
            return (1, date.max)

    for column in board.values():
        column.sort(key=key)
    return board


# --- follow-up reminders (#39) ------------------------------------------------

def add_followup_reminder(
    conn: sqlite3.Connection, job_id: int, due_at: str, title: str | None = None
) -> int:
    """Link a follow-up reminder to a job (reuses the reminder table)."""
    from .planner import add_reminder

    job = get_job(conn, job_id)
    if job is None:
        raise ValueError(f"no job #{job_id}")
    text = title or f"Follow up: {job['company']} — {job['role']}"
    return add_reminder(conn, "follow_up", ref_table="job", ref_id=job_id,
                        title=text, due_at=due_at)
