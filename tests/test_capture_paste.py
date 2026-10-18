import pytest

from cdesk.capture.paste import add_capture, capture_hash


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


def test_capture_hash_is_stable():
    assert capture_hash("hello") == capture_hash("hello")
    assert capture_hash("hello") != capture_hash("hello ")


def test_add_capture_stores_and_tags_origin(conn):
    rid, created = add_capture(conn, "fixed the parser bug", origin="opencode")
    assert created is True
    row = conn.execute("SELECT * FROM capture WHERE id=?", (rid,)).fetchone()
    assert row["origin"] == "opencode"
    assert row["source"] == "paste"
    assert row["content_hash"] == capture_hash("fixed the parser bug")


def test_add_capture_dedupes_same_body(conn):
    rid1, created1 = add_capture(conn, "same body", origin="gemini")
    rid2, created2 = add_capture(conn, "same body", origin="claude-acct-2")
    assert created1 is True
    assert created2 is False
    assert rid2 is None
    assert conn.execute("SELECT COUNT(*) FROM capture").fetchone()[0] == 1


def test_add_capture_rejects_empty(conn):
    with pytest.raises(ValueError):
        add_capture(conn, "   \n  ")


def test_add_capture_default_origin(conn, monkeypatch):
    monkeypatch.setenv("CDESK_ORIGIN", "claude-acct-2")
    rid, _ = add_capture(conn, "from claude")
    row = conn.execute("SELECT origin FROM capture WHERE id=?", (rid,)).fetchone()
    assert row["origin"] == "claude-acct-2"


def test_happened_at_defaults_to_now(conn):
    rid, _ = add_capture(conn, "today work")
    row = conn.execute("SELECT happened_at FROM capture WHERE id=?", (rid,)).fetchone()
    assert row["happened_at"]  # ISO timestamp
