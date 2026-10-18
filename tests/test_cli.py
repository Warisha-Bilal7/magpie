from typer.testing import CliRunner

from cdesk.cli import app

runner = CliRunner()


def test_help_works():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Content Desk" in result.output


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_journal_stub_runs_end_to_end():
    result = runner.invoke(app, ["journal", "--day", "2026-10-18"])
    assert result.exit_code == 0
    assert "stub line" in result.output


def test_draft_stub_runs_end_to_end():
    result = runner.invoke(app, ["draft", "--brief", "shipped the capture parser"])
    assert result.exit_code == 0
    assert "shipped the capture parser" in result.output


def test_stubs_for_future_milestones():
    for cmd in (["nudge"], ["ics"]):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0
