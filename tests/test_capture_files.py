import pytest

from cdesk.capture.files import capture_file, is_capturable


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


def test_is_capturable(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("# hi", encoding="utf-8")
    txt = tmp_path / "note.txt"
    txt.write_text("hi", encoding="utf-8")
    py = tmp_path / "script.py"
    py.write_text("x = 1", encoding="utf-8")
    assert is_capturable(md)
    assert is_capturable(txt)
    assert not is_capturable(py)


def test_capture_file_uses_filename_as_title(conn, tmp_path):
    p = tmp_path / "weekly_sync_notes.md"
    p.write_text("Met with the team about the launch.", encoding="utf-8")
    rid, created = capture_file(conn, p, origin="opencode")
    assert created
    row = conn.execute("SELECT * FROM capture WHERE id=?", (rid,)).fetchone()
    assert row["title"] == "weekly sync notes"
    assert row["source"] == "file"
    assert row["origin"] == "opencode"
    assert row["tags"] == "md"


def test_capture_file_dedupes_on_redrop(conn, tmp_path):
    p = tmp_path / "same.md"
    p.write_text("body", encoding="utf-8")
    _, created1 = capture_file(conn, p)
    _, created2 = capture_file(conn, p)
    assert created1 is True
    assert created2 is False


def test_capture_file_rejects_non_text(conn, tmp_path):
    p = tmp_path / "image.png"
    p.write_bytes(b"\x89PNG")
    with pytest.raises(ValueError):
        capture_file(conn, p)
