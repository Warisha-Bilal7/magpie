import pytest

from cdesk.capture.paste import add_capture
from cdesk.db import current_version, init_db, list_captures, list_origins, search_captures


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_fts_search_finds_body_match(conn):
    add_capture(conn, "rewrote the FTS triggers for capture", origin="opencode")
    add_capture(conn, "planned the society social", origin="gemini")
    hits = search_captures(conn, "triggers")
    assert len(hits) == 1
    assert "FTS" in hits[0]["body"]


def test_fts_search_finds_title_match(conn):
    add_capture(conn, "bodies here", origin="x", title="Deploy checklist")
    hits = search_captures(conn, "checklist")
    assert len(hits) == 1


def test_fts_search_phrase_query(conn):
    add_capture(conn, "shipped the capture inbox today", origin="a")
    add_capture(conn, "the inbox needs a redesign", origin="b")
    hits = search_captures(conn, '"capture inbox"')
    assert len(hits) == 1
    assert hits[0]["origin"] == "a"


def test_fts_no_matches(conn):
    add_capture(conn, "something", origin="a")
    assert search_captures(conn, "zebra") == []


def test_fts_stays_in_sync_after_delete(conn):
    rid, _ = add_capture(conn, "temporarily noted zebra work", origin="a")
    assert len(search_captures(conn, "zebra")) == 1
    conn.execute("DELETE FROM capture WHERE id=?", (rid,))
    conn.commit()
    assert search_captures(conn, "zebra") == []


def test_fts_stays_in_sync_after_update(conn):
    rid, _ = add_capture(conn, "original words here", origin="a")
    conn.execute("UPDATE capture SET body='completely new words' WHERE id=?", (rid,))
    conn.commit()
    assert search_captures(conn, "original") == []
    assert len(search_captures(conn, "completely")) == 1


def test_list_captures_newest_first(conn):
    add_capture(conn, "older", origin="a")
    add_capture(conn, "newer", origin="a")
    rows = list_captures(conn)
    assert [r["body"] for r in rows] == ["newer", "older"]


def test_list_origins_distinct_sorted(conn):
    add_capture(conn, "one", origin="gemini")
    add_capture(conn, "two", origin="claude-acct-2")
    add_capture(conn, "three", origin="gemini")
    assert list_origins(conn) == ["claude-acct-2", "gemini"]


def test_migration_v2_applied():
    c = init_db(":memory:")
    assert current_version(c) == 2
    triggers = c.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    names = {t["name"] for t in triggers}
    assert "capture_fts_insert" in names
    assert "capture_fts_delete" in names
    assert "capture_fts_update" in names
    c.close()


def test_migrate_from_v1_applies_v2(tmp_path):
    from cdesk.db import SCHEMA_VERSION, connect, migrate

    db = tmp_path / "old.db"
    conn = connect(db)
    conn.executescript(
        "CREATE TABLE capture (id INTEGER PRIMARY KEY, source TEXT NOT NULL,"
        " origin TEXT, title TEXT, body TEXT NOT NULL, content_hash TEXT UNIQUE,"
        " happened_at TEXT, captured_at TEXT DEFAULT CURRENT_TIMESTAMP,"
        " project_id INTEGER, tags TEXT);"
        "CREATE VIRTUAL TABLE capture_fts USING fts5(title, body);"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    migrate(conn)
    assert current_version(conn) == SCHEMA_VERSION
    conn.close()
