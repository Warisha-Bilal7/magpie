"""Journal page: entries with each line expandable to its source captures."""

import streamlit as st

from cdesk.db import captures_by_ids, entry_lines, init_db, list_journal_entries

st.set_page_config(page_title="Journal", page_icon="📔", layout="wide")
st.title("Journal")

conn = init_db()
entries = list_journal_entries(conn, limit=60)

if not entries:
    st.info("No entries yet. Generate one with `cdesk journal --day YYYY-MM-DD`.")
    st.stop()

kind_filter = st.radio("Kind", ["all", "daily", "weekly"], horizontal=True)
for e in entries:
    if kind_filter != "all" and e["kind"] != kind_filter:
        continue
    lines = entry_lines(conn, e["id"])
    status_icon = "✅" if e["status"] == "approved" else "📝"
    with st.expander(f"{status_icon} {e['day']} · {e['kind']} · {len(lines)} line(s)"):
        if not lines:
            st.caption("No lines stored for this entry.")
        for ln in lines:
            st.markdown(f"**{ln['text']}**")
            cited = captures_by_ids(conn, ln["capture_ids"])
            if not cited:
                st.caption("no cited captures found")
            for cap in cited.values():
                origin = cap.get("origin") or "unknown"
                title = cap.get("title") or "(untitled)"
                with st.popover(f"#{cap['id']} · {origin} · {title}"):
                    st.write(cap.get("body") or "")
                    st.caption(f"happened_at: {cap.get('happened_at')}")
conn.close()
