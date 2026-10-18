"""Planner tests: due_nudges, nudge text, status flow, reminders, to_ics.
M5 issues #31, #32, #35, #36.
"""

import json
from datetime import date, datetime, timezone

import pytest

from cdesk.planner import (
    due_nudges,
    drafts_ready,
    nudge_text,
    scheduled_events,
    set_post_status,
    to_ics,
)


# --- due_nudges (#32) -------------------------------------------------------

WORKSPACES = [
    {"id": 1, "name": "Substack", "cadence_days": 7},
    {"id": 2, "name": "LinkedIn", "cadence_days": 3},
    {"id": 3, "name": "Society", "cadence_days": None},
]
TODAY = date(2026, 10, 18)


def test_never_posted_is_nudged():
    out = due_nudges(WORKSPACES, {}, TODAY)
    by_name = {n["workspace"]: n for n in out}
    assert "Substack" in by_name
    assert by_name["Substack"]["days_since"] is None
    assert by_name["Substack"]["overdue_by"] is None


def test_on_time_is_not_nudged():
    last = {1: date(2026, 10, 15), 2: date(2026, 10, 17)}  # gaps 3 < 7, 1 < 3
    out = due_nudges(WORKSPACES, last, TODAY)
    assert out == []


def test_overdue_reports_gap_and_overdue_by():
    last = {1: date(2026, 10, 5), 2: date(2026, 10, 14)}  # gaps 13 (over 7), 4 (over 3)
    out = {n["workspace"]: n for n in due_nudges(WORKSPACES, last, TODAY)}
    assert out["Substack"]["days_since"] == 13
    assert out["Substack"]["overdue_by"] == 6
    assert out["LinkedIn"]["days_since"] == 4
    assert out["LinkedIn"]["overdue_by"] == 1


def test_no_cadence_workspace_skipped():
    last = {3: date(2026, 1, 1)}
    out = due_nudges(WORKSPACES, last, TODAY)
    assert all(n["workspace"] != "Society" for n in out)


def test_exact_cadence_gap_is_nudged():
    last = {1: date(2026, 10, 11)}  # gap == 7
    out = due_nudges(WORKSPACES, last, TODAY)
    assert any(n["workspace"] == "Substack" for n in out)


# --- nudge text (#36) -------------------------------------------------------

def test_nudge_text_overdue():
    text = nudge_text({"workspace": "Substack", "days_since": 9, "overdue_by": 2,
                       "cadence_days": 7})
    assert text == "9 days since your last Substack post (2 days over your cadence)."


def test_nudge_text_never_posted():
    text = nudge_text({"workspace": "LinkedIn", "days_since": None, "overdue_by": None,
                       "cadence_days": 3})
    assert text == "No LinkedIn post yet — your cadence is every 3 days."


# --- drafts ready (#36) -----------------------------------------------------

DRAFTS = [
    {"id": 1, "status": "draft", "workspace_id": 1},
    {"id": 2, "status": "draft", "workspace_id": 2},
    {"id": 3, "status": "scheduled", "workspace_id": 1},
    {"id": 4, "status": "published", "workspace_id": 1},
]


def test_drafts_ready_lists_only_draft_status():
    out = drafts_ready(DRAFTS, workspace_id=1)
    assert [p["id"] for p in out] == [1]
    out_all = drafts_ready(DRAFTS)
    assert [p["id"] for p in out_all] == [1, 2]


# --- status flow (#31) ------------------------------------------------------

@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def post(conn):
    from cdesk.db import store_post
    from cdesk.workspaces import create_workspace
    ws = create_workspace(conn, "LI", kind="linkedin")
    return store_post(conn, ws["id"], "A clean draft body.")


def test_draft_to_approved_to_scheduled_to_published(conn, post):
    set_post_status(conn, post, "approved")
    set_post_status(conn, post, "scheduled", scheduled_at="2026-10-20T09:00:00+00:00")
    set_post_status(conn, post, "published", published_at="2026-10-20T09:05:00+00:00")
    from cdesk.db import get_post
    row = get_post(conn, post)
    assert row["status"] == "published"
    assert row["scheduled_at"] == "2026-10-20T09:00:00+00:00"
    assert row["published_at"] == "2026-10-20T09:05:00+00:00"


def test_cannot_publish_directly_from_draft(conn, post):
    with pytest.raises(ValueError):
        set_post_status(conn, post, "published")


def test_cannot_skip_from_draft_to_scheduled(conn, post):
    with pytest.raises(ValueError):
        set_post_status(conn, post, "scheduled", scheduled_at="2026-10-20T09:00:00+00:00")


def test_scheduled_requires_a_time(conn, post):
    set_post_status(conn, post, "approved")
    with pytest.raises(ValueError):
        set_post_status(conn, post, "scheduled")


def test_unknown_status_rejected(conn, post):
    with pytest.raises(ValueError):
        set_post_status(conn, post, "launched")


def test_unschedule_back_to_approved(conn, post):
    set_post_status(conn, post, "approved")
    set_post_status(conn, post, "scheduled", scheduled_at="2026-10-20T09:00:00+00:00")
    set_post_status(conn, post, "approved")
    from cdesk.db import get_post
    assert get_post(conn, post)["status"] == "approved"


# --- reminders (#33) --------------------------------------------------------

def test_reminder_roundtrip(conn):
    from cdesk.planner import add_reminder, complete_reminder, list_reminders
    rid = add_reminder(conn, "post", ref_table="post", ref_id=5,
                       title="Ship the Substack draft", due_at="2026-10-19T10:00:00+00:00")
    rows = list_reminders(conn)
    assert rows[0]["title"] == "Ship the Substack draft"
    assert rows[0]["done"] == 0
    complete_reminder(conn, rid)
    assert list_reminders(conn) == []
    assert len(list_reminders(conn, include_done=True)) == 1


# --- to_ics (#35) ------------------------------------------------------------

def test_to_ics_basic_structure():
    start = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    out = to_ics([{"uid": "1", "title": "Ship the post", "start": start, "minutes": 30}])
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert out.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VEVENT" in out
    assert "UID:1@content-desk" in out
    assert "DTSTART:20261020T090000Z" in out
    assert "DTEND:20261020T093000Z" in out
    assert "SUMMARY:Ship the post" in out


def test_to_ics_escapes_special_chars():
    start = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    out = to_ics([{"uid": "2", "title": "a,b;c\nd", "start": start}])
    assert "SUMMARY:a\\,b\\;c\\nd" in out


def test_to_ics_default_duration():
    start = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    out = to_ics([{"uid": "3", "title": "x", "start": start}])
    assert "DTEND:20261020T093000Z" in out  # 30-minute default


def test_scheduled_events_from_posts():
    posts = [
        {"id": 7, "title": None, "body_md": "hi", "scheduled_at": "2026-10-20T09:00:00+00:00"},
        {"id": 8, "title": "Big launch", "body_md": "hi", "scheduled_at": None},
        {"id": 9, "title": None, "body_md": "hi", "scheduled_at": "not-a-date"},
    ]
    events = scheduled_events(posts)
    assert len(events) == 1
    assert events[0]["uid"] == "7"
    assert events[0]["title"].startswith("Draft #7")
