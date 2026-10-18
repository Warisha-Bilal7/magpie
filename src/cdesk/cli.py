"""Content Desk CLI. See docs/PLAN.md section 4 (repo layout).

M1: capture (add/file/git/chat), inbox, search, origins, watch.
M2+: journal, draft, nudge, ics, context against real data.
(The command is `cdesk`, not `desk` — on Windows `desk` collides with desk.cpl.)

Capture bodies are never printed by the CLI (AGENTS.md: no bodies in logs);
listings show id, date, origin and title only.
"""

import json
import sys
from datetime import date

import typer

from . import __version__
from .config import EMBED_MODEL, MODEL_NAME, PLATFORM_RULES, default_origin, ensure_dirs

app = typer.Typer(help="Content Desk — local-first work journal and posting desk.", no_args_is_help=True)


@app.callback()
def _main() -> None:
    ensure_dirs()


def _open_db():
    from .db import init_db
    return init_db()


def _fmt_capture(row) -> str:
    origin = row["origin"] or "unknown"
    title = row["title"] or "(untitled)"
    return f"#{row['id']:>4}  {row['captured_at'][:10]}  [{origin}]  {title}"


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
    text: str | None = typer.Option(None, "--text", "-t", help="Capture text (omit to read stdin)."),
    file: str | None = typer.Option(None, "--file", "-f", help="Capture a markdown/text file."),
    title: str | None = typer.Option(None, "--title", help="Optional title."),
    origin: str | None = typer.Option(None, "--origin", "-o", help='e.g. "claude-acct-2", "gemini".'),
    tags: str | None = typer.Option(None, "--tags", help="Comma-free tag string."),
) -> None:
    """Add a capture to the inbox: text, stdin, or a file. Deduped by content hash."""
    from .capture.files import capture_file
    from .capture.paste import add_capture

    conn = _open_db()
    try:
        if file:
            rid, created = capture_file(conn, file, origin=origin)
        else:
            body = text if text is not None else sys.stdin.read()
            rid, created = add_capture(conn, body, source="paste", origin=origin,
                                       title=title, tags=tags)
        if created:
            typer.echo(f"Captured #{rid} from origin={origin or default_origin()}.")
        else:
            typer.echo("Duplicate — already in the inbox.")
            raise typer.Exit(code=0)
    finally:
        conn.close()


@app.command("import-git")
def import_git(
    repo: str = typer.Argument(..., help="Path to a git repository."),
    since: str = typer.Option("1 week ago", "--since", help='git --since, e.g. "1 week ago".'),
) -> None:
    """Capture a repo's commits: one note per repo per day."""
    from .capture.git import add_git_captures

    conn = _open_db()
    try:
        results = add_git_captures(conn, repo, since)
    except Exception as e:
        typer.echo(f"git capture failed: {e}")
        raise typer.Exit(code=1)
    finally:
        conn.close()
    created = sum(1 for _, c in results if c)
    typer.echo(f"{created} new day note(s), {len(results) - created} duplicate(s).")


@app.command()
def chat(
    path: str = typer.Argument(..., help="Chat export file (JSON or markdown transcript)."),
    origin: str | None = typer.Option(None, "--origin", "-o", help="Which AI account/tool."),
) -> None:
    """Import a chat export; unrecognised formats fall back to a plain paste."""
    from .capture.chat_export import add_chat_export

    conn = _open_db()
    try:
        results = add_chat_export(conn, path, origin=origin)
    except Exception as e:
        typer.echo(f"chat import failed: {e}")
        raise typer.Exit(code=1)
    finally:
        conn.close()
    created = sum(1 for _, c in results if c)
    typer.echo(f"{created} new conversation(s), {len(results) - created} duplicate(s).")


@app.command()
def inbox(
    limit: int = typer.Option(15, "--limit", "-n", help="How many recent captures."),
    origin: str | None = typer.Option(None, "--origin", "-o", help="Filter by origin."),
) -> None:
    """List recent captures (titles only — bodies are never printed)."""
    from .db import list_captures, list_origins

    conn = _open_db()
    try:
        rows = list_captures(conn, limit=max(limit * 3, limit) if origin else limit)
        if origin:
            rows = [r for r in rows if (r["origin"] or "") == origin][:limit]
    finally:
        conn.close()
    if not rows:
        typer.echo("Inbox is empty. Add something with `cdesk add`.")
        return
    for row in rows:
        typer.echo(_fmt_capture(row))
    known = list_origins(conn) if False else None  # origins listed via `cdesk origins`


@app.command()
def search(
    query: str = typer.Argument(..., help="FTS5 query (try quotes for phrases)."),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Full-text search over captures (titles and bodies)."""
    from .db import search_captures

    conn = _open_db()
    try:
        try:
            rows = search_captures(conn, query, limit=limit)
        except Exception as e:
            typer.echo(f"bad query: {e}")
            raise typer.Exit(code=1)
    finally:
        conn.close()
    if not rows:
        typer.echo("No matches.")
        return
    for row in rows:
        typer.echo(_fmt_capture(row))


@app.command()
def origins() -> None:
    """List origins seen so far (which AI account or tool captures came from)."""
    from .db import list_origins

    conn = _open_db()
    try:
        names = list_origins(conn)
    finally:
        conn.close()
    if not names:
        typer.echo(f"No origins yet (default is '{default_origin()}', override with --origin or CDESK_ORIGIN).")
        return
    for name in names:
        typer.echo(name)


@app.command()
def watch(
    origin: str | None = typer.Option(None, "--origin", "-o", help="Origin for dropped files."),
) -> None:
    """Watch the drop folder (data/drop) and capture new markdown/text files."""
    import time

    from .capture.watcher import start_watcher
    from .config import DROP_DIR

    conn = _open_db()
    observer = start_watcher(conn, origin=origin)
    typer.echo(f"Watching {DROP_DIR} — drop .md/.txt files. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    conn.close()


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
