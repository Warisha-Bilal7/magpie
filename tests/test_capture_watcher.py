import pytest

from cdesk.capture.watcher import DropHandler


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


def test_handle_path_captures_markdown(conn, tmp_path):
    p = tmp_path / "dropped.md"
    p.write_text("dropped notes", encoding="utf-8")
    handler = DropHandler(conn, origin="drop-folder")
    result = handler.handle_path(p)
    assert result is not None
    rid, created = result
    assert created
    row = conn.execute("SELECT origin FROM capture WHERE id=?", (rid,)).fetchone()
    assert row["origin"] == "drop-folder"


def test_handle_path_skips_non_text(conn, tmp_path):
    p = tmp_path / "image.png"
    p.write_bytes(b"\x89PNG")
    handler = DropHandler(conn)
    assert handler.handle_path(p) is None


def test_handle_path_skips_empty_file(conn, tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("   ", encoding="utf-8")
    handler = DropHandler(conn)
    assert handler.handle_path(p) is None


def test_handle_path_missing_file_is_swallowed(conn, tmp_path):
    handler = DropHandler(conn)
    assert handler.handle_path(tmp_path / "gone.md") is None


def test_handle_path_dedupes(conn, tmp_path):
    p = tmp_path / "twice.md"
    p.write_text("same content", encoding="utf-8")
    handler = DropHandler(conn)
    _, created1 = handler.handle_path(p)
    _, created2 = handler.handle_path(p)
    assert created1 is True
    assert created2 is False
