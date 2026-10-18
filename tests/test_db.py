import sqlite3

import pytest

from cdesk.db import (
    INIT_SCHEMA,
    SCHEMA_VERSION,
    connect,
    current_version,
    init_db,
    insert_capture,
    migrate,
    search_captures,
)

TABLES = [
    "workspace", "project", "capture", "journal_entry", "journal_line",
    "post", "past_post", "idea", "job", "reminder",
]


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_init_creates_all_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    for t in TABLES:
        assert t in names, f"missing table {t}"
    assert "capture_fts" in names


def test_user_version_set(conn):
    assert current_version(conn) == SCHEMA_VERSION


def test_migrate_idempotent(conn):
    migrate(conn)
    migrate(conn)
    assert current_version(conn) == SCHEMA_VERSION


def test_connect_creates_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "dir" / "cdesk.db"
    c = connect(db)
    migrate(c)
    assert db.exists()
    c.close()


def _cap(**kw):
    base = {"source": "paste", "origin": "test", "title": "T", "body": "did a thing",
            "content_hash": "h1", "happened_at": "2026-10-18"}
    base.update(kw)
    return base


def test_insert_and_search_capture(conn):
    rowid = insert_capture(conn, _cap())
    assert rowid is not None
    assert conn.execute("SELECT COUNT(*) FROM capture").fetchone()[0] == 1
    hits = search_captures(conn, "thing")
    assert len(hits) == 1
    assert hits[0]["id"] == rowid


def test_insert_dupe_hash_rejected(conn):
    assert insert_capture(conn, _cap()) is not None
    assert insert_capture(conn, _cap(title="other")) is None
    assert conn.execute("SELECT COUNT(*) FROM capture").fetchone()[0] == 1


def test_check_constraints_reject_bad_values(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO workspace (name, kind) VALUES ('x', 'not-a-kind')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO post (workspace_id, status) VALUES (1, 'nope')"
        )


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO post (workspace_id) VALUES (999)"
        )
