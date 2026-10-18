"""Drafts page: generate drafts, see fact/rules warnings in red, repurpose."""

import json

import streamlit as st

from cdesk.db import get_post, init_db, list_posts
from cdesk.graphs.draft import build_draft_graph, repurpose_post
from cdesk.workspaces import list_workspaces

st.set_page_config(page_title="Drafts", page_icon="📝", layout="wide")
st.title("Drafts")

conn = init_db()
workspaces = list_workspaces(conn)

if not workspaces:
    st.info("Create a workspace first (Workspaces page).")
    conn.close()
    st.stop()

ws_names = [w["name"] for w in workspaces]
ws_by_name = {w["name"]: w for w in workspaces}

with st.sidebar:
    st.subheader("New draft")
    pick = st.selectbox("Workspace", ws_names, key="draft_ws")
    source = st.radio("Source", ["Brief", "Journal entry", "Existing post"], key="draft_src")
    brief = st.text_area("Brief", key="draft_brief",
                         placeholder="announce the workshop on 4 Nov")
    entries = conn.execute(
        "SELECT id, day, kind FROM journal_entry ORDER BY day DESC, id DESC LIMIT 20"
    ).fetchall()
    entry_id = None
    post_id = None
    if source == "Journal entry":
        if entries:
            choice = st.selectbox(
                "Journal entry",
                entries,
                format_func=lambda e: f"#{e['id']} {e['kind']} {e['day']}",
                key="draft_entry",
            )
            entry_id = choice["id"]
        else:
            st.info("No journal entries yet.")
    elif source == "Existing post":
        posts = list_posts(conn)
        if posts:
            choice = st.selectbox(
                "Post", posts,
                format_func=lambda p: f"#{p['id']} [{p['status']}] ws#{p['workspace_id']}",
                key="draft_post",
            )
            post_id = choice["id"]
        else:
            st.info("No posts yet.")

    if st.button("Generate draft", type="primary"):
        if source == "Brief" and not brief.strip():
            st.error("Write a brief first.")
        else:
            kind = {"Brief": "freeform", "Journal entry": "journal", "Existing post": "post"}[source]
            ids = {"journal": [entry_id] if entry_id else [],
                   "post": [post_id] if post_id else []}.get(kind, [])
            with st.spinner("Drafting..."):
                result = build_draft_graph().invoke({
                    "conn": conn,
                    "workspace_id": ws_by_name[pick]["id"],
                    "brief": brief,
                    "source_kind": kind,
                    "source_ids": ids,
                })
            st.session_state["last_draft"] = result

last = st.session_state.get("last_draft")
if last:
    st.subheader(f"Draft #{last.get('post_id', 0)}")
    if last.get("used_fallback"):
        st.warning("Template fallback was used (model unavailable).")
    for w in last.get("warnings", []):
        st.error(w)
    st.write(last.get("draft", ""))

st.subheader("Saved drafts")
rows = list_posts(conn)
if not rows:
    st.caption("Nothing saved yet.")
for p in rows:
    warnings = json.loads(p["warnings"]) if p["warnings"] else []
    label = f"#{p['id']} [{p['status']}] workspace #{p['workspace_id']}"
    if warnings:
        label += f" — {len(warnings)} warning(s)"
    with st.expander(label):
        st.write(p["body_md"])
        for w in warnings:
            st.error(w)
        targets = [n for n in ws_names if ws_by_name[n]["id"] != p["workspace_id"]]
        if targets:
            c1, c2 = st.columns([4, 1])
            target = c1.selectbox("Repurpose to", targets, key=f"reto_{p['id']}")
            if c2.button("Go", key=f"re_{p['id']}"):
                with st.spinner("Repurposing..."):
                    result = repurpose_post(conn, p["id"], ws_by_name[target]["id"])
                st.session_state["last_draft"] = result
                st.rerun()

conn.close()
