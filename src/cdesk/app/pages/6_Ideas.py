"""Ideas: cards by status, effort/impact scores, next step, duplicate warnings."""

import streamlit as st

from cdesk.db import init_db
from cdesk.ideas import (
    STATUSES,
    create_idea,
    find_duplicates,
    list_ideas,
    update_idea,
)

st.set_page_config(page_title="Ideas", page_icon="💡", layout="wide")
st.title("Ideas")

conn = init_db()

STATUS_ICONS = {
    "spark": "✨",
    "researching": "🔎",
    "building": "🔨",
    "shipped": "🚀",
    "parked": "🅿️",
}

with st.sidebar:
    st.subheader("New idea")
    title = st.text_input("Title", key="idea_title")
    note = st.text_area("Note", key="idea_note")
    status = st.selectbox("Status", STATUSES, key="idea_status")
    c1, c2 = st.columns(2)
    effort = c1.slider("Effort", 1, 5, 3, key="idea_effort")
    impact = c2.slider("Impact", 1, 5, 3, key="idea_impact")
    next_step = st.text_input("Next step", key="idea_next")
    if st.button("Add idea", type="primary"):
        if not title.strip():
            st.error("Give the idea a title.")
        else:
            idea = create_idea(conn, title, note=note or None, status=status,
                               effort=effort, impact=impact,
                               next_step=next_step or None)
            with st.spinner("Checking for near-duplicates..."):
                try:
                    dups = find_duplicates(conn, title, note or None,
                                           exclude_id=idea["id"])
                except Exception:
                    dups = []
            st.session_state["last_idea"] = idea
            st.session_state["last_dups"] = dups
            st.rerun()

last = st.session_state.pop("last_idea", None)
if last:
    st.success(f"Added idea #{last['id']}: {last['title']}")
for dup in st.session_state.pop("last_dups", []):
    st.warning(f"Possible duplicate: #{dup['id']} {dup['title']} "
               f"(score {dup['score']:.2f})")

status_filter = st.multiselect("Filter by status", STATUSES, default=list(STATUSES))
ideas = [i for i in list_ideas(conn) if i["status"] in status_filter]

if not ideas:
    st.info("No ideas yet. Add one in the sidebar.")
else:
    cols = st.columns(len(STATUSES))
    for col, status in zip(cols, STATUSES):
        with col:
            in_status = [i for i in ideas if i["status"] == status]
            st.subheader(f"{STATUS_ICONS[status]} {status.title()} ({len(in_status)})")
            if not in_status:
                st.caption("empty")
            for idea in in_status:
                with st.container(border=True):
                    st.markdown(f"**#{idea['id']} {idea['title']}**")
                    effort = idea["effort"] or "?"
                    impact = idea["impact"] or "?"
                    st.caption(f"effort {effort}/5 · impact {impact}/5")
                    if idea.get("note"):
                        st.write(idea["note"])
                    if idea.get("next_step"):
                        st.caption(f"next: {idea['next_step']}")
                    new_status = st.selectbox(
                        "Move to", STATUSES,
                        index=STATUSES.index(idea["status"]),
                        key=f"move_{idea['id']}", label_visibility="collapsed")
                    if new_status != idea["status"]:
                        update_idea(conn, idea["id"], status=new_status)
                        st.rerun()

conn.close()
