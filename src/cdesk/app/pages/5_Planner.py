"""Planner: week/month schedule, reminders, weekly review with nudges."""

from datetime import date, datetime, timedelta

import streamlit as st

from cdesk.db import init_db, list_journal_entries, list_posts
from cdesk.planner import (
    add_reminder,
    complete_reminder,
    drafts_ready,
    due_nudges,
    last_published_dates,
    list_reminders,
    nudge_text,
    set_post_status,
)
from cdesk.workspaces import list_workspaces

st.set_page_config(page_title="Planner", page_icon="🗓️", layout="wide")
st.title("Planner")

conn = init_db()
workspaces = list_workspaces(conn)
posts = list_posts(conn)

tab_week, tab_month, tab_reminders, tab_review = st.tabs(
    ["This week", "Month", "Reminders", "Weekly review"]
)


def _scheduled_in(start: date, end: date) -> list[dict]:
    out = []
    for p in posts:
        if p["status"] != "scheduled" or not p["scheduled_at"]:
            continue
        try:
            day = datetime.fromisoformat(p["scheduled_at"]).date()
        except ValueError:
            continue
        if start <= day <= end:
            out.append(p)
    return out


def _show_schedule(rows: list[dict]) -> None:
    if not rows:
        st.info("Nothing scheduled in this range.")
        return
    for p in rows:
        when = p["scheduled_at"][:16].replace("T", " ")
        c1, c2, c3 = st.columns([2, 5, 2])
        c1.write(when)
        c2.write(f"#{p['id']} ws#{p['workspace_id']}")
        if c3.button("Publish", key=f"pub_{p['id']}"):
            set_post_status(conn, p["id"], "published",
                            published_at=datetime.now().astimezone().isoformat())
            st.rerun()


with tab_week:
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    st.caption(f"{start} to {end}")
    _show_schedule(_scheduled_in(start, end))

with tab_month:
    anchor = st.date_input("Month", date.today(), key="month")
    first = anchor.replace(day=1)
    if first.month == 12:
        last = first.replace(year=first.year + 1, month=1) - timedelta(days=1)
    else:
        last = first.replace(month=first.month + 1) - timedelta(days=1)
    _show_schedule(_scheduled_in(first, last))

with tab_reminders:
    rows = list_reminders(conn)
    if not rows:
        st.info("No open reminders.")
    for r in rows:
        c1, c2 = st.columns([6, 1])
        c1.write(f"{r['due_at'][:16]} — {r['title']} ({r['kind']})")
        if c2.button("✓", key=f"done_{r['id']}"):
            complete_reminder(conn, r["id"])
            st.rerun()
    with st.expander("Add reminder"):
        title = st.text_input("Title", key="rem_title")
        due = st.text_input("Due (ISO)", date.today().isoformat(), key="rem_due")
        kind = st.selectbox("Kind", ["post", "deadline", "follow_up", "review"], key="rem_kind")
        if st.button("Add") and title.strip():
            add_reminder(conn, kind, title=title.strip(), due_at=due)
            st.rerun()

with tab_review:
    today = date.today()
    nudges = due_nudges(workspaces, last_published_dates(conn), today)
    if not nudges:
        st.success("All channels on cadence.")
    for n in nudges:
        st.warning(nudge_text(n))
    ready = drafts_ready(posts)
    if ready:
        st.info(f"Drafts ready for review: {len(ready)} "
                f"(ids: {', '.join(str(p['id']) for p in ready)}) — see the Drafts page.")
    entries = list_journal_entries(conn, limit=7)
    st.subheader("Recent journal entries")
    if not entries:
        st.info("No journal entries yet.")
    for e in entries:
        st.markdown(f"- **{e['day']}** ({e['kind']}, {e['status']})")

conn.close()
