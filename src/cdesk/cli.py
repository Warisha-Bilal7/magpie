"""Content Desk CLI. See docs/PLAN.md section 4 (repo layout).

M0: `cdesk init`, `cdesk doctor` and `cdesk journal|draft` (stub graphs) work.
M1+ fills in add/journal/draft/nudge/ics/context against real data.
(The command is `cdesk`, not `desk` — on Windows `desk` collides with desk.cpl.)
"""

import json
from datetime import date

import typer

from . import __version__
from .config import EMBED_MODEL, MODEL_NAME, PLATFORM_RULES, ensure_dirs

app = typer.Typer(help="Content Desk — local-first work journal and posting desk.", no_args_is_help=True)


@app.callback()
def _main() -> None:
    ensure_dirs()


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def init() -> None:
    """Create the data directory and the SQLite schema."""
    from .db import SCHEMA_VERSION, init_db

    conn = init_db()
    conn.close()
    typer.echo(f"Database ready (schema v{SCHEMA_VERSION}).")


@app.command()
def doctor() -> None:
    """Check Ollama, the text model and the embedding model."""
    from .llm import embed, ollama_available, models_present

    if not ollama_available():
        typer.echo("Ollama: NOT reachable. Run `ollama serve` and try again.")
        raise typer.Exit(code=1)
    typer.echo("Ollama: ok")

    status = models_present(MODEL_NAME, EMBED_MODEL)
    for name, ok in status.items():
        typer.echo(f"Model {name}: {'ok' if ok else 'MISSING — run `ollama pull ' + name + '`'}")

    if not all(status.values()):
        raise typer.Exit(code=1)

    try:
        vec = embed(["content desk smoke test"])
        typer.echo(f"Embeddings: ok ({len(vec[0])} dims)")
    except Exception as e:
        typer.echo(f"Embeddings: FAILED — {e}")
        raise typer.Exit(code=1)


@app.command()
def add(
    text: str | None = typer.Option(None, "--text", "-t", help="Capture text (or omit to read stdin)."),
    origin: str | None = typer.Option(None, "--origin", "-o", help='Where it came from, e.g. "claude-acct-2".'),
) -> None:
    """Quick-add a capture to the inbox (M1)."""
    typer.echo("Capture lands in M1. For now nothing was saved.")
    if text:
        typer.echo(f"(would store text from origin={origin or 'unset'}, {len(text)} chars)")


@app.command()
def journal(
    day: str | None = typer.Option(None, "--day", "-d", help="yyyy-mm-dd; defaults to today."),
    weekly: bool = typer.Option(False, "--weekly", help="Generate a weekly entry."),
) -> None:
    """Run the journal graph over a day's captures (stub in M0, real in M2)."""
    from .graphs.journal import build_journal_graph

    day = day or date.today().isoformat()
    result = build_journal_graph().invoke(
        {"day": day, "kind": "weekly" if weekly else "daily", "captures": []}
    )
    typer.echo(f"Journal ({day}): {len(result.get('lines', []))} stub line(s).")
    if result.get("warnings"):
        typer.echo("Warnings: " + json.dumps(result["warnings"]))


@app.command()
def draft(
    brief: str = typer.Option("", "--brief", "-b", help="What the draft should say."),
    workspace: str = typer.Option("personal", "--workspace", "-w", help="Target workspace kind."),
) -> None:
    """Run the draft graph (stub in M0, real in M4)."""
    from .graphs.draft import build_draft_graph

    rules = PLATFORM_RULES.get(workspace, {})
    result = build_draft_graph().invoke(
        {"brief": brief, "source_kind": "freeform", "rules": rules}
    )
    typer.echo(result.get("draft", "(no draft)"))


@app.command()
def nudge() -> None:
    """Show posting nudges (M5)."""
    typer.echo("Nudges land in M5.")


@app.command()
def ics() -> None:
    """Export planner events as .ics (M5)."""
    typer.echo(".ics export lands in M5.")


@app.command()
def context(
    project: str = typer.Argument(..., help="Project name for the brief."),
) -> None:
    """Generate a paste-ready context pack for a project (M6)."""
    typer.echo(f"Context pack for '{project}' lands in M6.")


if __name__ == "__main__":
    app()
