import pytest
from typer.testing import CliRunner

from cdesk.cli import app

runner = CliRunner()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the CLI at a throwaway database."""
    import cdesk.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "test.db")
    return tmp_path


def test_help_works():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Content Desk" in result.output


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_add_text_and_dedupe(db):
    r1 = runner.invoke(app, ["add", "-t", "shipped the capture inbox", "-o", "opencode"])
    assert r1.exit_code == 0
    assert "Captured #1" in r1.output
    r2 = runner.invoke(app, ["add", "-t", "shipped the capture inbox", "-o", "gemini"])
    assert r2.exit_code == 0
    assert "Duplicate" in r2.output


def test_add_file(db, tmp_path):
    p = tmp_path / "meeting_notes.md"
    p.write_text("Discussed the launch plan.", encoding="utf-8")
    r = runner.invoke(app, ["add", "--file", str(p), "-o", "claude-acct-2"])
    assert r.exit_code == 0
    assert "Captured" in r.output


def test_inbox_lists_without_bodies(db):
    runner.invoke(app, ["add", "-t", "secret body should not print", "-o", "opencode"])
    r = runner.invoke(app, ["inbox"])
    assert r.exit_code == 0
    assert "secret body should not print" not in r.output
    assert "[opencode]" in r.output


def test_search(db):
    runner.invoke(app, ["add", "-t", "fixed the watcher race condition", "-o", "opencode"])
    r = runner.invoke(app, ["search", "watcher"])
    assert r.exit_code == 0
    assert "[opencode]" in r.output


def test_search_no_matches(db):
    r = runner.invoke(app, ["search", "zzzznotfound"])
    assert r.exit_code == 0
    assert "No matches" in r.output


def test_origins(db):
    runner.invoke(app, ["add", "-t", "one", "-o", "gemini"])
    runner.invoke(app, ["add", "-t", "two", "-o", "claude-acct-2"])
    r = runner.invoke(app, ["origins"])
    assert "claude-acct-2" in r.output
    assert "gemini" in r.output


def test_import_git(db, tmp_path):
    import os
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-10-17T10:00:00",
               GIT_COMMITTER_DATE="2026-10-17T10:00:00")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=T",
         "commit", "-m", "cli test commit"],
        check=True, env=env, capture_output=True,
    )
    r = runner.invoke(app, ["import-git", str(repo), "--since", "2026-10-01"])
    assert r.exit_code == 0
    assert "1 new day note(s)" in r.output


def test_chat_import(db, tmp_path):
    import json
    p = tmp_path / "chat.json"
    p.write_text(json.dumps({"title": "t", "messages": [{"role": "user", "content": "hi"}]}),
                 encoding="utf-8")
    r = runner.invoke(app, ["chat", str(p), "-o", "gemini"])
    assert r.exit_code == 0
    assert "1 new conversation(s)" in r.output


def test_journal_stub_runs_end_to_end(db):
    result = runner.invoke(app, ["journal", "--day", "2026-10-18"])
    assert result.exit_code == 0
    assert "stub line" in result.output


def test_draft_stub_runs_end_to_end(db):
    result = runner.invoke(app, ["draft", "--brief", "shipped the capture parser"])
    assert result.exit_code == 0
    assert "shipped the capture parser" in result.output


def test_stubs_for_future_milestones(db):
    for cmd in (["nudge"], ["ics"]):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0
