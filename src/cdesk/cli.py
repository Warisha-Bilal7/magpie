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
from .config import EMBED_MODEL, MODEL_NAME, default_origin, ensure_dirs

# Windows consoles default to cp1252; non-ASCII output (BOMs, smart quotes
# from imported posts) must never crash a command.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="Content Desk — local-first work journal and posting desk.", no_args_is_help=True)
ws_app = typer.Typer(help="Workspaces: channels, rules and the past-post voice corpus.", no_args_is_help=True)
idea_app = typer.Typer(help="Idea cards: status, effort/impact scores, near-duplicate detection.", no_args_is_help=True)
job_app = typer.Typer(help="Job tracker: kanban, deadlines, follow-up reminders, tailoring.", no_args_is_help=True)
app.add_typer(ws_app, name="workspace")
app.add_typer(idea_app, name="idea")
app.add_typer(job_app, name="job")


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
    project: str | None = typer.Option(None, "--project", "-p", help="Assign to a project (created on first mention)."),
) -> None:
    """Add a capture to the inbox: text, stdin, or a file. Deduped by content hash."""
    from .capture.files import capture_file
    from .capture.paste import add_capture
    from .db import get_or_create_project

    conn = _open_db()
    try:
        project_id = None
        if project:
            project_id = get_or_create_project(conn, project)["id"]
        if file:
            rid, created = capture_file(conn, file, origin=origin)
        else:
            body = text if text is not None else sys.stdin.read()
            rid, created = add_capture(conn, body, source="paste", origin=origin,
                                       title=title, tags=tags, project_id=project_id)
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
    workspace: str = typer.Option(..., "--workspace", "-w", help="Target workspace name."),
    journal_entry: int | None = typer.Option(None, "--journal-entry", help="Draft from a journal entry id."),
    post: int | None = typer.Option(None, "--post", help="Draft from an existing post id."),
    idea: int | None = typer.Option(None, "--idea", help="Draft from an idea card id."),
) -> None:
    """Run the draft graph: gather, write, fact-check, rules-check, save."""
    from .graphs.draft import build_draft_graph

    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        picked = [k for k, v in [("journal", journal_entry), ("post", post), ("idea", idea)] if v is not None]
        if len(picked) > 1:
            typer.echo("Pick at most one of --journal-entry/--post/--idea.")
            raise typer.Exit(code=1)
        if picked:
            kind, sid = picked[0], {"journal": journal_entry, "post": post, "idea": idea}[picked[0]]
            source_kind, source_ids = kind, [sid]
        else:
            if not brief.strip():
                typer.echo("Give a --brief or a source (--journal-entry/--post/--idea).")
                raise typer.Exit(code=1)
            source_kind, source_ids = "freeform", []
        result = build_draft_graph().invoke({
            "conn": conn, "workspace_id": ws["id"], "brief": brief,
            "source_kind": source_kind, "source_ids": source_ids,
        })
    finally:
        conn.close()
    tag = " (template fallback)" if result.get("used_fallback") else ""
    typer.echo(f"Draft #{result.get('post_id', 0)} for {workspace}{tag}")
    typer.echo(result.get("draft", "(no draft)"))
    for w in result.get("warnings", []):
        typer.echo(f"  warning: {w}")


@app.command()
def drafts(
    workspace: str = typer.Option("", "--workspace", "-w", help="Filter by workspace name."),
) -> None:
    """List saved drafts with their warning counts (bodies not printed)."""
    from .db import list_posts

    conn = _open_db()
    try:
        ws_id = None
        if workspace:
            ws_id = _ws_or_die(conn, workspace)["id"]
        rows = list_posts(conn, workspace_id=ws_id)
    finally:
        conn.close()
    if not rows:
        typer.echo("No drafts yet.")
        return
    for p in rows:
        warnings = json.loads(p["warnings"]) if p["warnings"] else []
        flag = f"  {len(warnings)} warning(s)" if warnings else ""
        typer.echo(f"#{p['id']} [{p['status']}] ws#{p['workspace_id']}{flag}")


@app.command()
def repurpose(
    post_id: int = typer.Argument(..., help="Post id to repurpose."),
    workspace: str = typer.Option(..., "--workspace", "-w", help="Target workspace name."),
) -> None:
    """Re-draft an existing post into another workspace's voice and rules."""
    from .graphs.draft import repurpose_post

    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        result = repurpose_post(conn, post_id, ws["id"])
    except ValueError as e:
        typer.echo(str(e))
        raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(f"Repurposed post #{post_id} -> draft #{result.get('post_id', 0)} for {workspace}")
    typer.echo(result.get("draft", "(no draft)"))
    for w in result.get("warnings", []):
        typer.echo(f"  warning: {w}")


@app.command()
def nudge() -> None:
    """Show posting nudges and drafts waiting for review."""
    from .planner import drafts_ready, due_nudges, last_published_dates, nudge_text
    from .workspaces import list_workspaces

    conn = _open_db()
    try:
        workspaces = list_workspaces(conn)
        nudges = due_nudges(workspaces, last_published_dates(conn), date.today())
        drafts = drafts_ready([
            dict(r) for r in conn.execute(
                "SELECT id, workspace_id, status FROM post WHERE status = 'draft'"
            ).fetchall()
        ])
    finally:
        conn.close()
    if not nudges and not drafts:
        typer.echo("All channels on cadence. Nothing waiting either.")
        return
    for n in nudges:
        typer.echo(f"- {nudge_text(n)}")
    if drafts:
        typer.echo(f"Drafts ready for review: {len(drafts)} "
                   f"(ids: {', '.join(str(p['id']) for p in drafts)})")


@app.command()
def ics(
    out: str = typer.Option("", "--out", "-o", help="Write the .ics here (default: data/exports/)."),
) -> None:
    """Export scheduled posts as an .ics calendar file."""
    from pathlib import Path

    from .config import EXPORT_DIR
    from .db import list_posts
    from .planner import scheduled_events, to_ics

    conn = _open_db()
    try:
        posts = list_posts(conn, status="scheduled")
    finally:
        conn.close()
    events = scheduled_events(posts)
    text = to_ics(events)
    path = Path(out) if out else EXPORT_DIR / "content-desk.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    typer.echo(f"Wrote {len(events)} event(s) to {path}")


@app.command()
def schedule(
    post_id: int = typer.Argument(...),
    at: str = typer.Option(..., "--at", help="ISO time, e.g. 2026-10-20T09:00:00+00:00"),
) -> None:
    """Approve-and-schedule a draft (must already be approved)."""
    from .planner import set_post_status

    conn = _open_db()
    try:
        try:
            row = set_post_status(conn, post_id, "scheduled", scheduled_at=at)
        except ValueError as e:
            typer.echo(str(e))
            raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(f"Post #{row['id']} scheduled for {row['scheduled_at']}")


@app.command()
def status(
    post_id: int = typer.Argument(...),
    new_status: str = typer.Argument(..., help="idea|draft|approved|scheduled|published"),
    at: str = typer.Option("", "--at", help="ISO time (scheduled/published)."),
) -> None:
    """Move a post through its status flow (validated transitions)."""
    from .planner import set_post_status

    conn = _open_db()
    try:
        try:
            row = set_post_status(conn, post_id, new_status,
                                  scheduled_at=at or None,
                                  published_at=at or None)
        except ValueError as e:
            typer.echo(str(e))
            raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(f"Post #{row['id']} is now '{row['status']}'")


@app.command()
def tailor(
    job_id: int = typer.Argument(..., help="Job id to tailor bullets for."),
) -> None:
    """Run the job tailor graph: match journal evidence, draft cited bullets."""
    from .graphs.job_tailor import build_job_tailor_graph
    from .jobs import get_job

    conn = _open_db()
    try:
        job = get_job(conn, job_id)
        if job is None:
            typer.echo(f"No job #{job_id}.")
            raise typer.Exit(code=1)
        result = build_job_tailor_graph().invoke({
            "conn": conn, "job_id": job_id, "jd_text": job.get("jd_text") or "",
            "company": job["company"], "role": job["role"],
        })
    finally:
        conn.close()
    tag = " (template fallback)" if result.get("used_fallback") else ""
    typer.echo(f"Tailored bullets for {job['company']} — {job['role']}{tag}")
    for b in result.get("bullets", []):
        typer.echo(f"  - {b['text']}  [cites: {b['cites']}]")
    if not result.get("bullets"):
        typer.echo("  (no bullets — no grounded evidence matched, or all were dropped)")
    for w in result.get("warnings", []):
        typer.echo(f"  warning: {w}")


@app.command()
def cover(
    job_id: int = typer.Argument(..., help="Job id to draft a cover letter for."),
) -> None:
    """Draft a cover letter grounded in cited journal lines, fact-checked."""
    from .graphs.job_tailor import draft_cover_letter
    from .jobs import get_job

    conn = _open_db()
    try:
        if get_job(conn, job_id) is None:
            typer.echo(f"No job #{job_id}.")
            raise typer.Exit(code=1)
        result = draft_cover_letter(conn, job_id)
    except ValueError as e:
        typer.echo(str(e))
        raise typer.Exit(code=1)
    finally:
        conn.close()
    tag = " (template fallback)" if result.get("used_fallback") else ""
    typer.echo(f"Cover letter (artifact #{result.get('artifact_id', 0)}){tag}")
    typer.echo(result.get("letter", "(no letter)"))
    for w in result.get("warnings", []):
        typer.echo(f"  warning: {w}")


@app.command()
def context(
    project: str = typer.Argument(..., help="Project name for the brief."),
    days: int = typer.Option(14, "--days", "-d", help="Look-back window in days."),
) -> None:
    """Generate a paste-ready context pack for a project (F8, issue #42)."""
    from .context_pack import context_pack

    conn = _open_db()
    try:
        md = context_pack(conn, project, days=days)
    finally:
        conn.close()
    typer.echo(md, nl=False)


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
    from .workspaces import add_banned_phrase, effective_rules, get_workspace
    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        add_banned_phrase(conn, ws["id"], phrase)
        rules = effective_rules(get_workspace(conn, ws["id"]))
        typer.echo(f"Banned phrases for {ws['name']}: {rules['banned']}")
    finally:
        conn.close()


@ws_app.command("unban")
def ws_unban(
    phrase: str = typer.Argument(...),
    workspace: str = typer.Option(..., "-w", "--workspace"),
) -> None:
    """Remove a banned phrase from a workspace's rules."""
    from .workspaces import effective_rules, get_workspace, remove_banned_phrase
    conn = _open_db()
    try:
        ws = _ws_or_die(conn, workspace)
        remove_banned_phrase(conn, ws["id"], phrase)
        rules = effective_rules(get_workspace(conn, ws["id"]))
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


# --- idea subcommands (M6, issues #37, #38) ----------------------------------

def _fmt_idea(row) -> str:
    effort = f"e{row['effort']}" if row.get("effort") else "e?"
    impact = f"i{row['impact']}" if row.get("impact") else "i?"
    step = f"  next: {row['next_step']}" if row.get("next_step") else ""
    return f"#{row['id']:>3} [{row['status']}] {effort}/{impact}  {row['title']}{step}"


@idea_app.command("add")
def idea_add(
    title: str = typer.Argument(...),
    note: str = typer.Option("", "--note", "-n"),
    status: str = typer.Option("spark", "--status", "-s", help="spark|researching|building|shipped|parked"),
    effort: int | None = typer.Option(None, "--effort", "-e", help="1-5."),
    impact: int | None = typer.Option(None, "--impact", "-i", help="1-5."),
    next_step: str = typer.Option("", "--next", help="One concrete next action."),
    source: list[int] = typer.Option([], "--source", help="Capture id to link (repeatable)."),
) -> None:
    """Create an idea card."""
    from .ideas import create_idea

    conn = _open_db()
    try:
        try:
            idea = create_idea(conn, title, note=note or None, status=status,
                               effort=effort, impact=impact,
                               next_step=next_step or None,
                               source_ids=source or None)
        except ValueError as e:
            typer.echo(str(e))
            raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(_fmt_idea(idea))


@idea_app.command("list")
def idea_list(
    status: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List idea cards (newest updated first)."""
    from .ideas import list_ideas

    conn = _open_db()
    try:
        rows = list_ideas(conn, status=status or None)
    finally:
        conn.close()
    if not rows:
        typer.echo("No ideas yet. Add one with `cdesk idea add`.")
        return
    for row in rows:
        typer.echo(_fmt_idea(row))


@idea_app.command("status")
def idea_status(
    idea_id: int = typer.Argument(...),
    new_status: str = typer.Argument(..., help="spark|researching|building|shipped|parked"),
) -> None:
    """Move an idea to a new status."""
    from .ideas import STATUSES, update_idea

    conn = _open_db()
    try:
        if new_status not in STATUSES:
            typer.echo(f"status must be one of {STATUSES}")
            raise typer.Exit(code=1)
        try:
            idea = update_idea(conn, idea_id, status=new_status)
        except ValueError as e:
            typer.echo(str(e))
            raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(f"Idea #{idea['id']} -> '{idea['status']}'")


@idea_app.command("dupes")
def idea_dupes(
    idea_id: int = typer.Argument(..., help="Idea to check for near-duplicates."),
    threshold: float = typer.Option(0.82, "--threshold", "-t", help="Cosine similarity threshold 0-1."),
) -> None:
    """Find near-duplicate ideas (embedding cosine, keyword fallback offline)."""
    from .ideas import find_duplicates, get_idea

    conn = _open_db()
    try:
        idea = get_idea(conn, idea_id)
        if idea is None:
            typer.echo(f"No idea #{idea_id}.")
            raise typer.Exit(code=1)
        try:
            dups = find_duplicates(conn, idea["title"], idea.get("note"),
                                   threshold=threshold, exclude_id=idea_id)
        except Exception as e:
            typer.echo(f"duplicate check failed (Ollama unavailable?): {e}")
            raise typer.Exit(code=1)
    finally:
        conn.close()
    if not dups:
        typer.echo(f"No near-duplicates at threshold {threshold}.")
        return
    for d in dups:
        typer.echo(f"#{d['id']}  score={d['score']:.3f}  {d['title']}")


# --- job subcommands (M6, issues #39, #40, #41) ------------------------------

def _fmt_job(row) -> str:
    deadline = f"  due {row['deadline']}" if row.get("deadline") else ""
    applied = f"  applied {row['applied_on']}" if row.get("applied_on") else ""
    return f"#{row['id']:>3} [{row['status']}] {row['company']} — {row['role']}{deadline}{applied}"


@job_app.command("add")
def job_add(
    company: str = typer.Argument(...),
    role: str = typer.Argument(...),
    url: str = typer.Option("", "--url"),
    deadline: str = typer.Option("", "--deadline", help="yyyy-mm-dd."),
    jd_file: str = typer.Option("", "--jd", help="Path to a job-description text file."),
) -> None:
    """Add a job card."""
    from pathlib import Path

    from .jobs import add_job

    jd_text = ""
    if jd_file:
        jd_text = Path(jd_file).read_text(encoding="utf-8", errors="replace")
    conn = _open_db()
    try:
        job = add_job(conn, company, role, url=url or None,
                      deadline=deadline or None, jd_text=jd_text or None)
    finally:
        conn.close()
    typer.echo(_fmt_job(job))


@job_app.command("list")
def job_list(
    status: str = typer.Option("", "--status", "-s", help="Filter by status."),
) -> None:
    """List job cards."""
    from .jobs import list_jobs

    conn = _open_db()
    try:
        rows = list_jobs(conn, status=status or None)
    finally:
        conn.close()
    if not rows:
        typer.echo("No jobs yet. Add one with `cdesk job add`.")
        return
    for row in rows:
        typer.echo(_fmt_job(row))


@job_app.command("status")
def job_status(
    job_id: int = typer.Argument(...),
    new_status: str = typer.Argument(..., help="saved|applied|interviewing|offer|closed"),
) -> None:
    """Move a job through its kanban (validated transitions)."""
    from .jobs import set_job_status

    conn = _open_db()
    try:
        try:
            job = set_job_status(conn, job_id, new_status)
        except ValueError as e:
            typer.echo(str(e))
            raise typer.Exit(code=1)
    finally:
        conn.close()
    typer.echo(f"Job #{job['id']} -> '{job['status']}'")


@job_app.command("board")
def job_board() -> None:
    """Show the kanban: jobs grouped by status, deadlines first."""
    from .jobs import kanban

    conn = _open_db()
    try:
        board = kanban(conn)
    finally:
        conn.close()
    if not any(board.values()):
        typer.echo("Board is empty.")
        return
    for status, jobs in board.items():
        typer.echo(f"{status.upper()} ({len(jobs)})")
        for j in jobs:
            typer.echo(f"  {_fmt_job(j)}")


@job_app.command("followup")
def job_followup(
    job_id: int = typer.Argument(...),
    days: int = typer.Option(7, "--days", "-d", help="Remind in N days."),
    note: str = typer.Option("", "--note"),
) -> None:
    """Set a follow-up reminder for an application."""
    from datetime import datetime, timedelta, timezone

    from .jobs import add_followup_reminder, get_job

    conn = _open_db()
    try:
        job = get_job(conn, job_id)
        if job is None:
            typer.echo(f"No job #{job_id}.")
            raise typer.Exit(code=1)
        due = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        title = note or f"Follow up: {job['company']} — {job['role']}"
        rem_id = add_followup_reminder(conn, job_id, due, title)
    finally:
        conn.close()
    typer.echo(f"Reminder #{rem_id} set for {due}: {title}")


if __name__ == "__main__":
    app()
