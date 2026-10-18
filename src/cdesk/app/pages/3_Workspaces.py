"""Workspaces page: settings, banned-phrase editor, voice corpus and examples."""

import json

import streamlit as st

from cdesk.db import init_db
from cdesk.voice import voice_examples
from cdesk.workspaces import (
    KINDS,
    add_banned_phrase,
    add_past_post,
    create_workspace,
    delete_workspace,
    effective_rules,
    get_workspace,
    import_posts,
    index_workspace_embeddings,
    list_past_posts,
    list_workspaces,
    parse_posts_json,
    parse_posts_text,
    remove_banned_phrase,
    update_workspace,
)

st.set_page_config(page_title="Workspaces", page_icon="🎙️", layout="wide")
st.title("Workspaces")

conn = init_db()
workspaces = list_workspaces(conn)

with st.sidebar:
    st.subheader("Your channels")
    names = [w["name"] for w in workspaces]
    if names:
        pick = st.selectbox("Workspace", names)
        ws = get_workspace(conn, name=pick)
    else:
        st.info("No workspaces yet.")
        ws = None
    with st.expander("Create workspace"):
        new_name = st.text_input("Name", key="new_ws_name")
        new_kind = st.selectbox("Kind", KINDS, key="new_ws_kind")
        new_cadence = st.number_input("Cadence (days between posts)", 0, 365, 0, key="new_ws_cad")
        new_audience = st.text_input("Audience", key="new_ws_aud")
        if st.button("Create") and new_name.strip():
            try:
                create_workspace(conn, new_name.strip(), kind=new_kind,
                                 cadence_days=new_cadence or None,
                                 audience=new_audience.strip() or None)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

if ws is None:
    st.stop()

rules = effective_rules(ws)

tab_settings, tab_bans, tab_voice = st.tabs(["Settings", "Banned phrases", "Voice corpus"])

with tab_settings:
    st.write(f"**Kind:** {ws['kind']} · **Cadence:** "
             f"{ws['cadence_days'] or '—'} days · **Audience:** {ws['audience'] or '—'}")
    col1, col2 = st.columns(2)
    cad = st.number_input("Cadence (days)", 0, 365, ws["cadence_days"] or 0, key="edit_cad")
    aud = st.text_input("Audience", ws["audience"] or "", key="edit_aud")
    max_chars = st.number_input("Max characters", 100, 200_000, int(rules["max_chars"]), key="edit_chars")
    max_tags = st.number_input("Max hashtags", 0, 30, int(rules["max_hashtags"]), key="edit_tags")
    if st.button("Save settings"):
        stored = dict(rules)
        stored["max_chars"] = int(max_chars)
        stored["max_hashtags"] = int(max_tags)
        update_workspace(conn, ws["id"], cadence_days=cad or None,
                         audience=aud.strip() or None, rules_json=json.dumps(stored))
        st.rerun()
    if st.button("Delete workspace", type="secondary"):
        delete_workspace(conn, ws["id"])
        st.rerun()

with tab_bans:
    st.caption("Phrases the drafter must never use. Grow the list from words you delete by hand.")
    banned = list(rules.get("banned", []))
    if not banned:
        st.caption("No banned phrases yet.")
    for phrase in banned:
        c1, c2 = st.columns([6, 1])
        c1.write(phrase)
        if c2.button("✕", key=f"unban_{phrase}"):
            remove_banned_phrase(conn, ws["id"], phrase)
            st.rerun()
    new_ban = st.text_input("Add phrase", key="new_ban")
    if st.button("Ban phrase") and new_ban.strip():
        add_banned_phrase(conn, ws["id"], new_ban.strip())
        st.rerun()

with tab_voice:
    st.caption("Past posts are the voice corpus. Drafts retrieve the 3 most similar as style examples.")
    posts = list_past_posts(conn, ws["id"])
    st.write(f"**{len(posts)} past posts** ({sum(1 for p in posts if p['indexed'])} indexed)")

    uploaded = st.file_uploader("Import posts (.txt with --- separators, or .json)", type=["txt", "md", "json"])
    if uploaded is not None and st.button("Import"):
        raw = uploaded.read().decode("utf-8", errors="replace")
        try:
            parsed = parse_posts_json(raw) if uploaded.name.endswith(".json") else parse_posts_text(raw)
            import_posts(conn, ws["id"], parsed)
            n = index_workspace_embeddings(conn, ws["id"])
            st.success(f"Imported {len(parsed)} post(s), indexed {n}.")
            st.rerun()
        except Exception as e:
            st.error(f"import failed: {e}")

    for p in posts[-10:]:
        with st.expander(f"#{p['id']} {'✅' if p['indexed'] else '⏳'} "
                         f"{p['body'][:60]}{'…' if len(p['body']) > 60 else ''}"):
            st.write(p["body"])
            if p["url"]:
                st.caption(p["url"])

    st.subheader("Voice examples")
    query = st.text_input("Query (what the next post is about)", key="voice_query")
    if st.button("Find examples") and query.strip():
        try:
            index_workspace_embeddings(conn, ws["id"])
            examples = voice_examples(conn, ws["id"], query, k=3)
            if not examples:
                st.info("No indexed past posts yet — import some above.")
            for i, ex in enumerate(examples, 1):
                st.markdown(f"**Example {i}**")
                st.write(ex["body"])
        except Exception as e:
            st.error(f"retrieval failed (is Ollama running?): {e}")

conn.close()
