"""Content Desk — Streamlit home. Run: streamlit run src/cdesk/app/Home.py"""

import streamlit as st

from cdesk.db import init_db, list_journal_entries

st.set_page_config(page_title="Content Desk", page_icon="📓", layout="wide")
st.title("Content Desk")

conn = init_db()
entries = list_journal_entries(conn, limit=10)
captures = conn.execute("SELECT COUNT(*) FROM capture").fetchone()[0]
conn.close()

c1, c2, c3 = st.columns(3)
c1.metric("Captures in inbox", captures)
c2.metric("Journal entries", len(entries))
c3.metric("This week", "→ Journal")

st.subheader("Recent journal entries")
if not entries:
    st.info("No journal entries yet. Run `cdesk journal --day YYYY-MM-DD` or use the Journal page.")
for e in entries[:5]:
    st.markdown(f"- **{e['day']}** ({e['kind']}, {e['status']})")

st.caption("Privacy: everything lives in local SQLite under data/. Nothing leaves this machine.")
