"""Job kanban, deadlines and follow-up reminders (M6 #39)."""

from datetime import date

import pytest

from cdesk.jobs import (
    add_followup_reminder,
    add_job,
    deadline_text,
    delete_job,
    due_follow_ups,
    get_job,
    kanban,
    list_jobs,
    set_job_status,
    update_job,
    upcoming_deadlines,
)

TODAY = date(2026, 10, 18)


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


# --- CRUD --------------------------------------------------------------------

def test_add_and_get_job(conn):
    j = add_job(conn, "Acme", "Backend Engineer", url="https://acme.dev/j/1",
                deadline="2026-10-25", jd_text="Python, SQLite")
    assert j["id"] > 0
    assert j["status"] == "saved"
    fetched = get_job(conn, j["id"])
    assert fetched["company"] == "Acme"
    assert fetched["jd_text"] == "Python, SQLite"


def test_add_rejects_empty_and_bad_status(conn):
    with pytest.raises(ValueError):
        add_job(conn, "  ", "Role")
    with pytest.raises(ValueError):
        add_job(conn, "Acme", "  ")
    with pytest.raises(ValueError):
        add_job(conn, "Acme", "Role", status="ghost")


def test_update_and_delete(conn):
    j = add_job(conn, "Acme", "Engineer")
    update_job(conn, j["id"], notes="referral from Sam", deadline="2026-11-01")
    assert get_job(conn, j["id"])["notes"] == "referral from Sam"
    with pytest.raises(ValueError):
        update_job(conn, j["id"], oops=1)
    delete_job(conn, j["id"])
    assert get_job(conn, j["id"]) is None


def test_list_filter(conn):
    add_job(conn, "A", "Role 1")
    add_job(conn, "B", "Role 2")
    assert len(list_jobs(conn)) == 2
    assert len(list_jobs(conn, status="saved")) == 2
    assert list_jobs(conn, status="offer") == []


# --- status flow (#39) ---------------------------------------------------------

def test_status_flow_saved_to_applied_stamps_applied_on(conn):
    j = add_job(conn, "Acme", "Engineer")
    moved = set_job_status(conn, j["id"], "applied")
    assert moved["status"] == "applied"
    assert moved["applied_on"]  # stamped so nudges can count


def test_status_flow_valid_transitions(conn):
    j = add_job(conn, "Acme", "Engineer")
    set_job_status(conn, j["id"], "applied")
    set_job_status(conn, j["id"], "interviewing")
    set_job_status(conn, j["id"], "offer")
    set_job_status(conn, j["id"], "closed")
    with pytest.raises(ValueError):
        set_job_status(conn, j["id"], "applied")  # closed is terminal


def test_status_flow_rejects_skipping_and_unknown(conn):
    j = add_job(conn, "Acme", "Engineer")
    with pytest.raises(ValueError):
        set_job_status(conn, j["id"], "offer")  # saved -> offer not allowed
    with pytest.raises(ValueError):
        set_job_status(conn, j["id"], "ghost")
    with pytest.raises(ValueError):
        set_job_status(conn, 999, "applied")


# --- follow-up nudges (#39) -----------------------------------------------------

def test_due_follow_ups_overdue_applied_job():
    jobs = [
        {"id": 1, "company": "A", "role": "R", "status": "applied",
         "applied_on": "2026-10-01"},   # 17 days ago
        {"id": 2, "company": "B", "role": "R", "status": "applied",
         "applied_on": "2026-10-16"},   # 2 days ago
        {"id": 3, "company": "C", "role": "R", "status": "interviewing",
         "applied_on": "2026-10-01"},
        {"id": 4, "company": "D", "role": "R", "status": "applied", "applied_on": None},
    ]
    out = due_follow_ups(jobs, TODAY, days=7)
    assert [j["id"] for j in out] == [1]
    assert out[0]["days_since_applied"] == 17
    assert out[0]["overdue_by"] == 10


def test_due_follow_ups_recent_applied_not_nudged():
    jobs = [{"id": 1, "status": "applied", "applied_on": "2026-10-15"}]
    assert due_follow_ups(jobs, TODAY, days=7) == []


def test_due_follow_ups_bad_date_ignored():
    jobs = [{"id": 1, "status": "applied", "applied_on": "not-a-date"}]
    assert due_follow_ups(jobs, TODAY) == []


def test_due_follow_ups_sorted_most_overdue_first():
    jobs = [
        {"id": 1, "status": "applied", "applied_on": "2026-10-14"},  # 4 days
        {"id": 2, "status": "applied", "applied_on": "2026-10-01"},  # 17 days
    ]
    out = due_follow_ups(jobs, TODAY, days=3)  # both past the 3-day threshold
    assert [j["id"] for j in out] == [2, 1]  # most overdue first


# --- deadlines (#39) ------------------------------------------------------------

def test_deadline_text_upcoming_today_passed():
    job = {"company": "Acme", "role": "Engineer", "deadline": "2026-10-21"}
    assert "in 3 day" in deadline_text(job, TODAY)
    job["deadline"] = "2026-10-18"
    assert "today" in deadline_text(job, TODAY)
    job["deadline"] = "2026-10-15"
    assert "passed 3 day" in deadline_text(job, TODAY)


def test_deadline_text_missing_or_bad_is_none():
    assert deadline_text({"deadline": None}, TODAY) is None
    assert deadline_text({"deadline": "soon"}, TODAY) is None


def test_upcoming_deadlines_soonest_first():
    jobs = [
        {"id": 1, "deadline": "2026-10-30"},
        {"id": 2, "deadline": "2026-10-20"},
        {"id": 3, "deadline": None},
        {"id": 4, "deadline": "2026-10-10"},   # overdue, still flagged
    ]
    out = upcoming_deadlines(jobs, TODAY, within_days=14)
    assert [j["id"] for j in out] == [4, 2, 1]
    assert out[0]["days_to_deadline"] == -8


# --- kanban board (#39) -----------------------------------------------------------

def test_kanban_groups_by_status_and_sorts_by_deadline(conn):
    a = add_job(conn, "A", "Role", status="saved", deadline="2026-10-25")
    b = add_job(conn, "B", "Role", status="saved", deadline="2026-10-20")
    c = add_job(conn, "C", "Role", status="saved")  # no deadline
    d = add_job(conn, "D", "Role", status="interviewing")
    board = kanban(conn, today=TODAY)
    assert set(board) == {"saved", "applied", "interviewing", "offer", "closed"}
    assert [j["id"] for j in board["saved"]] == [b["id"], a["id"], c["id"]]
    assert [j["id"] for j in board["interviewing"]] == [d["id"]]
    assert board["offer"] == []


# --- follow-up reminders (#39) -----------------------------------------------------

def test_add_followup_reminder_links_to_job(conn):
    j = add_job(conn, "Acme", "Engineer")
    rid = add_followup_reminder(conn, j["id"], due_at="2026-10-25T09:00:00+00:00")
    from cdesk.planner import list_reminders
    rows = list_reminders(conn)
    assert rows[0]["id"] == rid
    assert rows[0]["ref_table"] == "job"
    assert rows[0]["ref_id"] == j["id"]
    assert "Acme" in rows[0]["title"]


def test_add_followup_reminder_missing_job(conn):
    with pytest.raises(ValueError):
        add_followup_reminder(conn, 999, due_at="2026-10-25")
