import subprocess

import pytest

from cdesk.capture.git import add_git_captures, git_captures


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()

    def commit(msg, day):
        (r / "file.txt").write_text(msg, encoding="utf-8")
        subprocess.run(["git", "-C", str(r), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=T",
             "commit", "-m", msg, "--date", f"{day}T12:00:00"],
            check=True,
            env={"GIT_AUTHOR_DATE": f"{day}T12:00:00", "GIT_COMMITTER_DATE": f"{day}T12:00:00",
                 "PATH": __import__("os").environ["PATH"]},
        )

    subprocess.run(["git", "-C", str(r), "init"], check=True, capture_output=True)
    commit("first commit", "2026-10-14")
    commit("second commit same day", "2026-10-14")
    commit("next day work", "2026-10-15")
    return r


def test_one_note_per_repo_per_day(repo):
    caps = git_captures(str(repo), "2026-10-01")
    assert len(caps) == 2  # two busy days -> two notes
    day1 = next(c for c in caps if c["happened_at"] == "2026-10-14")
    assert "- first commit" in day1["body"]
    assert "- second commit same day" in day1["body"]
    assert day1["source"] == "git"
    assert day1["title"] == "Commits on 2026-10-14"


def test_git_captures_origin_is_repo_path(repo):
    caps = git_captures(str(repo), "2026-10-01")
    assert all(c["origin"].endswith("repo") for c in caps)


def test_add_git_captures_dedupes(repo):
    from cdesk.db import init_db

    conn = init_db(":memory:")
    first = add_git_captures(conn, str(repo), "2026-10-01")
    second = add_git_captures(conn, str(repo), "2026-10-01")
    assert all(created for _, created in first)
    assert not any(created for _, created in second)
    assert conn.execute("SELECT COUNT(*) FROM capture").fetchone()[0] == 2
    conn.close()


def test_git_captures_since_filters_days(repo):
    # full timestamp: bare "2026-10-15" is approxidate end-of-day in git >= 2.5x
    caps = git_captures(str(repo), "2026-10-15T00:00:00")
    assert len(caps) == 1
    assert caps[0]["happened_at"] == "2026-10-15"


def test_git_captures_empty_repo(tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    subprocess.run(["git", "-C", str(r), "init"], check=True, capture_output=True)
    assert git_captures(str(r), "2026-10-01") == []
