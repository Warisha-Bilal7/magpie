"""Content Desk CLI. See docs/PLAN.md section 4 (repo layout).

M1: capture (add/file/git/chat), inbox, search, origins, watch.
M2+: journal, draft, nudge, ics, context against real data.
(The command is `cdesk`, not `desk` — on Windows `desk` collides with desk.cpl.)

Capture bodies are never printed by the CLI (AGENTS.md: no bodies in logs);
listings show id, date, origin and title only.
"""

import sys
from datetime import date

import typer

from . import __version__
from .config import EMBED_MODEL, MODEL_NAME, PLATFORM_RULES, default_origin, ensure_dirs

app = typer.Typer(help="Content Desk — local-first work journal and posting desk.", no_args_is_help=True)
ws_app = typer.Typer(help="Workspaces: channels, rules and the past-post voice corpus.", no_args_is_help=True)
app.add_typer(ws_app, name="workspace")


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
    from .db import list_captures

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
    weekly: bool = typer.Option(False, "--weekly", help="Weekly digest from the week's daily lines."),
) -> None:
    """Run the journal graph over a day's captures (or the week's daily lines)."""
    from datetime import timedelta

    from .db import captures_by_ids, captures_for_day, daily_lines_between, init_db
    from .graphs.journal import build_journal_graph

    day = day or date.today().isoformat()
    conn = init_db()
    try:
        state: dict = {"model_name": MODEL_NAME}
        if weekly:
            start = date.fromisoformat(day)
            start = start - timedelta(days=start.weekday())  # Monday
            end = start + timedelta(days=6)
            source_lines = daily_lines_between(conn, start.isoformat(), end.isoformat())
            cap_ids = [c for ln in source_lines for c in ln["capture_ids"]]
            state.update({
                "day": start.isoformat(), "kind": "weekly",
                "source_lines": source_lines,
                "captures": list(captures_by_ids(conn, cap_ids).values()),
                "conn": conn,
            })
            if not source_lines:
                typer.echo(f"No daily journal lines in week of {start.isoformat()}.")
                return
        else:
            state.update({
                "day": day, "kind": "daily",
                "captures": captures_for_day(conn, day),
                "conn": conn,
            })
        result = build_journal_graph().invoke(state)
    finally:
        conn.close()

    tag = " (digest fallback)" if result.get("used_fallback") else ""
    typer.echo(f"Journal entry #{result.get('entry_id', 0)} ({result['kind']} {result['day']}){tag}")
    for ln in result.get("lines", []):
        typer.echo(f"  - {ln['text']}  [captures: {ln['cites']}]")
    for w in result.get("warnings", []):
        typer.echo(f"  warning: {w}")
    if not result.get("lines") and not result.get("warnings"):
        typer.echo("  (no lines)")


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


# --- workspace subcommands (M3) ---------------------------------------------

def _ws_or_die(conn, name: str) -> dict:
    from .workspaces import get_workspace
    ws = get_workspace(conn, name=name)
    if ws is None:
        typer.echo(f"No workspace named '{name}'. Create it with `cdesk workspace add`.")
        raise typer.Exit(code=1)
    return ws


@ws_app.command("add")
def ws_add(
    name: str = typer.Argument(...),
    kind: str = typer.Option(..., "-k", "--kind", help="substack|linkedin|society|personal|other"),
    cadence: int | None = typer.Option(None, "--cadence", help="Post every N days."),
    audience: str | None = typer.Option(None, "--audience", help="Who reads this channel."),
) -> None:
    """Create a workspace (one per channel)."""
    from .workspaces import create_workspace
    conn = _open_db()
    try:
        ws = create_workspace(conn, name, kind=kind, cadence_days=cadence, audience=audience)
    except ValueError as e:
        typer.echo(str(e))
        raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(f"Workspace #{ws['id']} {ws['name']} ({ws['kind']}) created.")


@ws_app.command("list")
def ws_list() -> None:
    """List workspaces with cadence and voice-corpus size."""
    from .workspaces import list_workspaces
    conn = _open_db()
    try:
        rows = list_workspaces(conn)
        for w in rows:
            n = conn.execute(
                "SELECT COUNT(*) FROM past_post WHERE workspace_id = ?", (w["id"],)
            ).fetchone()[0]
            cadence = f"every {w['cadence_days']}d" if w["cadence_days"] else "no cadence"
            typer.echo(f"#{w['id']} {w['name']} ({w['kind']}, {cadence}, {n} past posts)")
    finally:
        conn.close()


@ws_app.command("import-posts")
def ws_import_posts(
    file: str = typer.Argument(..., help="Text file (posts separated by ---) or JSON list."),
    workspace: str = typer.Option(..., "-w", "--workspace"),
) -> None:
    """Import past posts as the workspace's voice corpus, then index embeddings."""
    from pathlib import Path

    from .workspaces import import_posts, parse_posts_json, parse_posts_text
    p = Path(file)
    raw = p.read_text(encoding="utf-8", errors="replace")
    try:
        posts = parse_posts_json(raw) if p.suffix.lower() == ".json" else parse_posts_text(raw)
    except ValueError as e:
        typer.echo(f"could not parse: {e}")
        raise typer.Exit(code=1)
    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        ids = import_posts(conn, ws["id"], posts)
        typer.echo(f"Imported {len(ids)} past post(s) into {ws['name']}.")
        from .workspaces import index_workspace_embeddings
        try:
            n = index_workspace_embeddings(conn, ws["id"])
            typer.echo(f"Indexed embeddings for {n} post(s).")
        except Exception as e:
            typer.echo(f"Embeddings deferred (Ollama unavailable?): {e}")
    finally:
        conn.close()


@ws_app.command("ban")
def ws_ban(
    phrase: str = typer.Argument(...),
    workspace: str = typer.Option(..., "-w", "--workspace"),
) -> None:
    """Add a banned phrase to a workspace's rules (style lint)."""
    from .workspaces import add_banned_phrase, effective_rules
    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        add_banned_phrase(conn, ws["id"], phrase)
        rules = effective_rules(ws)
        typer.echo(f"Banned phrases for {ws['name']}: {rules['banned']}")
    finally:
        conn.close()


@ws_app.command("unban")
def ws_unban(
    phrase: str = typer.Argument(...),
    workspace: str = typer.Option(..., "-w", "--workspace"),
) -> None:
    """Remove a banned phrase from a workspace's rules."""
    from .workspaces import effective_rules, remove_banned_phrase
    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        remove_banned_phrase(conn, ws["id"], phrase)
        rules = effective_rules(ws)
        typer.echo(f"Banned phrases for {ws['name']}: {rules['banned']}")
    finally:
        conn.close()


@ws_app.command("voice")
def ws_voice(
    query: str = typer.Argument(..., help="Text to find similar past posts for."),
    workspace: str = typer.Option(..., "-w", "--workspace"),
    k: int = typer.Option(3, "-k"),
) -> None:
    """Show the k most similar past posts (the voice examples for drafting)."""
    from .voice import voice_examples
    from .workspaces import index_workspace_embeddings
    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        try:
            index_workspace_embeddings(conn, ws["id"])
            examples = voice_examples(conn, ws["id"], query, k=k)
        except Exception as e:
            typer.echo(f"voice retrieval failed (Ollama unavailable?): {e}")
            raise typer.Exit(code=1)
    finally:
        conn.close()
    if not examples:
        typer.echo("No indexed past posts yet. Import some with `cdesk workspace import-posts`.")
        return
    for i, ex in enumerate(examples, 1):
        preview = ex["body"].replace("\n", " ")[:100]
        typer.echo(f"{i}. #{ex['id']} {preview}")


if __name__ == "__main__":
    app()
