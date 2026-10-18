"""Jobs: kanban by status, deadlines, tailor bullets and cover letters."""

from datetime import date, datetime, timedelta, timezone

import streamlit as st

from cdesk.db import init_db
from cdesk.graphs.job_tailor import build_job_tailor_graph, draft_cover_letter
from cdesk.jobs import (
    STATUSES,
    add_followup_reminder,
    add_job,
    kanban,
    list_jobs,
)

st.set_page_config(page_title="Jobs", page_icon="💼", layout="wide")
st.title("Jobs")

conn = init_db()

STATUS_ICONS = {
    "saved": "📌",
    "applied": "📨",
    "interviewing": "🗣️",
    "offer": "🎉",
    "closed": "🚪",
}

with st.sidebar:
    st.subheader("New job")
    company = st.text_input("Company", key="job_company")
    role = st.text_input("Role", key="job_role")
    url = st.text_input("URL", key="job_url")
    deadline = st.date_input("Deadline", value=None, key="job_deadline")
    jd_text = st.text_area("Job description", key="job_jd")
    if st.button("Add job", type="primary"):
        if not company.strip() or not role.strip():
            st.error("Company and role are required.")
        else:
            add_job(conn, company, role, url=url or None,
                    deadline=deadline.isoformat() if deadline else None,
                    jd_text=jd_text or None)
            st.rerun()

board = kanban(conn)
if not any(board.values()):
    st.info("No jobs yet. Add one in the sidebar.")

cols = st.columns(len(STATUSES))
for col, status in zip(cols, STATUSES):
    with col:
        jobs = board[status]
        st.subheader(f"{STATUS_ICONS[status]} {status.title()} ({len(jobs)})")
        if not jobs:
            st.caption("empty")
        for job in jobs:
            with st.container(border=True):
                st.markdown(f"**#{job['id']} {job['company']}**")
                st.caption(job["role"])
                if job.get("deadline"):
                    st.caption(f"due {job['deadline']}")
                if job.get("applied_on"):
                    st.caption(f"applied {job['applied_on']}")

                move_options = [s for s in STATUSES if s != job["status"]]
                new_status = st.selectbox("Move to", ["—"] + move_options,
                                          key=f"jmove_{job['id']}")
                if new_status != "—":
                    from cdesk.jobs import set_job_status
                    try:
                        set_job_status(conn, job["id"], new_status)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.rerun()

                if st.button("Follow up in 7 days", key=f"jfu_{job['id']}"):
                    due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                    add_followup_reminder(conn, job["id"], due)
                    st.success("Reminder set.")

                if st.button("Tailor bullets", key=f"jt_{job['id']}"):
                    with st.spinner("Matching your journal evidence..."):
                        result = build_job_tailor_graph().invoke({
                            "conn": conn, "job_id": job["id"],
                            "jd_text": job.get("jd_text") or "",
                            "company": job["company"], "role": job["role"],
                        })
                    st.session_state[f"tailored_{job['id']}"] = result
                if st.session_state.get(f"tailored_{job['id']}"):
                    result = st.session_state[f"tailored_{job['id']}"]
                    if result.get("used_fallback"):
                        st.warning("Template fallback used (model unavailable).")
                    for b in result.get("bullets", []):
                        st.markdown(f"- {b['text']}  `[cites: {b['cites']}]`")
                    for w in result.get("warnings", []):
                        st.error(w)

                if st.button("Draft cover letter", key=f"jc_{job['id']}"):
                    with st.spinner("Drafting and fact-checking..."):
                        result = draft_cover_letter(conn, job["id"])
                    st.session_state[f"cover_{job['id']}"] = result
                if st.session_state.get(f"cover_{job['id']}"):
                    result = st.session_state[f"cover_{job['id']}"]
                    st.text_area("Cover letter", result.get("letter", ""),
                                 key=f"cover_text_{job['id']}", height=200)
                    for w in result.get("warnings", []):
                        st.error(w)

st.divider()
st.subheader("Upcoming deadlines")
from cdesk.jobs import deadline_text, upcoming_deadlines
deadlines = upcoming_deadlines(list_jobs(conn), date.today(), within_days=30)
if not deadlines:
    st.caption("No deadlines in the next 30 days.")
for job in deadlines:
    st.write(f"**{job['deadline']}** ({deadline_text(job, date.today())}) — "
             f"#{job['id']} {job['company']} ({job['role']})")

conn.close()
