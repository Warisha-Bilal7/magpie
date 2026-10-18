"""Context pack tests (F8, issue #42): journal lines, decisions, questions,
linked ideas. Deterministic — no model needed.
"""

import pytest

from cdesk.context_pack import (
    _is_decision,
    _is_question,
    context_pack,
    linked_ideas,
    project_capture_ids,
    project_journal_lines,
)
from cdesk.db import init_db, store_journal_entry


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def _add_capture(conn, body, tags=None, project_id=None):
    from cdesk.capture.paste import add_capture
    cap_id, _ = add_capture(conn, body, tags=tags, project_id=project_id)
    return cap_id


def _project(conn, name):
    from cdesk.db import get_or_create_project
    return get_or_create_project(conn, name)


# --- helpers ----------------------------------------------------------------

def test_is_decision_matches_verbs():
    assert _is_decision("Decided to use SQLite for storage.")
    assert _is_decision("We chose Postgres over MySQL.")
    assert _is_decision("Going with the simpler design.")
    assert not _is_decision("Wrote some tests today.")


def test_is_question_matches_trailing_question_mark():
    assert _is_question("Should we add caching?")
    assert _is_question("Next step?\n")
    assert not _is_question("Shipped the feature.")


# --- capture selection ------------------------------------------------------

def test_project_capture_ids_by_project_id(conn):
    proj = _project(conn, "magpie")
    cid = _add_capture(conn, "worked on the schema", project_id=proj["id"])
    assert project_capture_ids(conn, "magpie") == [cid]


def test_project_capture_ids_by_tag(conn):
    cid = _add_capture(conn, "talked about magpie at the meetup", tags="magpie,ai")
    assert cid in project_capture_ids(conn, "magpie")


def test_project_capture_ids_merges_project_and_tag_dedupes(conn):
    proj = _project(conn, "magpie")
    c1 = _add_capture(conn, "by project", project_id=proj["id"])
    c2 = _add_capture(conn, "by tag", tags="magpie")
    c3 = _add_capture(conn, "both", project_id=proj["id"], tags="magpie")
    ids = project_capture_ids(conn, "magpie")
    assert sorted(ids) == sorted({c1, c2, c3})


# --- journal lines ----------------------------------------------------------

def test_project_journal_lines_only_approved_and_linked(conn):
    proj = _project(conn, "magpie")
    cap = _add_capture(conn, "worked on tailoring", project_id=proj["id"])
    entry_id = store_journal_entry(conn, "2026-10-01", "daily", [
        {"text": "Shipped the tailoring graph", "cites": [cap]},
        {"text": "Unrelated line", "cites": [999]},
    ])
    conn.execute("UPDATE journal_entry SET status='approved' WHERE id=?",
                 (entry_id,))
    conn.commit()
    lines = project_journal_lines(conn, "magpie", days=36500)
    assert len(lines) == 1
    assert lines[0]["text"] == "Shipped the tailoring graph"
    assert lines[0]["day"] == "2026-10-01"


def test_project_journal_lines_excludes_unapproved(conn):
    proj = _project(conn, "magpie")
    cap = _add_capture(conn, "draft work", project_id=proj["id"])
    store_journal_entry(conn, "2026-10-01", "daily", [
        {"text": "Still drafting this entry", "cites": [cap]},
    ])  # status defaults to 'draft'
    assert project_journal_lines(conn, "magpie") == []


def test_project_journal_lines_respects_days_cutoff(conn):
    proj = _project(conn, "magpie")
    cap = _add_capture(conn, "old work", project_id=proj["id"])
    entry_id = store_journal_entry(conn, "2020-01-01", "daily", [
        {"text": "Very old line", "cites": [cap]},
    ])
    conn.execute("UPDATE journal_entry SET status='approved' WHERE id=?",
                 (entry_id,))
    conn.commit()
    assert project_journal_lines(conn, "magpie", days=30) == []
    assert len(project_journal_lines(conn, "magpie", days=36500)) == 1


# --- linked ideas -----------------------------------------------------------

def test_linked_ideas_by_source_capture(conn):
    proj = _project(conn, "magpie")
    cap = _add_capture(conn, "idea seed capture", project_id=proj["id"])
    from cdesk.ideas import create_idea
    create_idea(conn, "Ship the context pack", source_ids=[cap])
    ideas = linked_ideas(conn, "magpie")
    assert len(ideas) == 1
    assert ideas[0]["title"] == "Ship the context pack"


def test_linked_ideas_ignores_unrelated_sources(conn):
    _project(conn, "magpie")
    from cdesk.ideas import create_idea
    create_idea(conn, "Unrelated idea", source_ids=[999])
    assert linked_ideas(conn, "magpie") == []


# --- full pack --------------------------------------------------------------

def test_context_pack_sections_and_paste_ready(conn):
    proj = _project(conn, "magpie")
    cap = _add_capture(conn, "tailoring work", project_id=proj["id"])
    entry_id = store_journal_entry(conn, "2026-10-15", "daily", [
        {"text": "Decided to reuse the citation verifier for cover letters.",
         "cites": [cap]},
        {"text": "Should we surface duplicates inline or as a banner?",
         "cites": [cap]},
        {"text": "Reviewed the tailoring graph end to end.", "cites": [cap]},
    ])
    conn.execute("UPDATE journal_entry SET status='approved' WHERE id=?",
                 (entry_id,))
    conn.commit()
    from cdesk.ideas import create_idea
    create_idea(conn, "Inline duplicate warnings", source_ids=[cap])

    md = context_pack(conn, "magpie", days=36500)
    assert md.startswith("# Project brief: magpie")
    assert "## Recent journal lines" in md
    assert "## Decisions" in md
    assert "## Open questions" in md
    assert "## Linked ideas" in md
    assert "Decided to reuse the citation verifier" in md
    assert "Should we surface duplicates inline" in md
    assert "[spark] Inline duplicate warnings" in md


def test_context_pack_empty_project_still_renders(conn):
    md = context_pack(conn, "does-not-exist")
    assert "# Project brief: does-not-exist" in md
    assert "_(no approved journal lines matched this project yet)_" in md
    assert "_(none recorded in this window)_" in md
    assert "_(no idea cards linked to this project's captures)_" in md
