"""SQLite schema, migrations and helpers. See docs/PLAN.md section 5.

Schema changes MUST go through migrations: bump SCHEMA_VERSION, append SQL to
MIGRATIONS, and never edit an old migration in place.
"""

import json
import sqlite3
from pathlib import Path

from .config import DB_PATH, ensure_dirs

SCHEMA_VERSION = 3

INIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('substack','linkedin','society','personal','other')),
  cadence_days INTEGER,              -- target: post every N days
  rules_json TEXT,                   -- max_chars, max_hashtags, banned phrases, tone notes
  audience TEXT
);

CREATE TABLE IF NOT EXISTS project (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS capture (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,              -- paste | file | git | chat_export | quick
  origin TEXT,                       -- e.g. "claude-acct-2", "gemini", "opencode", repo path
  title TEXT,
  body TEXT NOT NULL,
  content_hash TEXT UNIQUE,          -- sha256 of body, for dedupe
  happened_at TEXT,                  -- when the work happened (ISO)
  captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
  project_id INTEGER REFERENCES project(id),
  tags TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS capture_fts USING fts5(title, body);

CREATE TABLE IF NOT EXISTS journal_entry (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,                 -- yyyy-mm-dd (week start for weekly entries)
  kind TEXT NOT NULL CHECK (kind IN ('daily','weekly')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS journal_line (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES journal_entry(id),
  text TEXT NOT NULL,
  capture_ids TEXT NOT NULL,         -- JSON list of capture ids (the receipts)
  embedding BLOB
);

CREATE TABLE IF NOT EXISTS post (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  title TEXT,
  body_md TEXT,
  status TEXT NOT NULL DEFAULT 'idea'
    CHECK (status IN ('idea','draft','approved','scheduled','published')),
  scheduled_at TEXT,
  published_at TEXT,
  source_ids TEXT,                   -- JSON: journal line ids / capture ids used
  parent_post_id INTEGER REFERENCES post(id),   -- repurposed from
  warnings TEXT                      -- JSON list from fact/rules checks
);

CREATE TABLE IF NOT EXISTS past_post (             -- voice corpus: your real published posts
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  body TEXT NOT NULL,
  url TEXT,
  published_at TEXT,
  embedding BLOB
);

CREATE TABLE IF NOT EXISTS idea (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'spark'
    CHECK (status IN ('spark','researching','building','shipped','parked')),
  effort INTEGER, impact INTEGER,    -- 1-5
  next_step TEXT,
  source_ids TEXT,                   -- JSON capture ids
  embedding BLOB,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job (
  id INTEGER PRIMARY KEY,
  company TEXT NOT NULL, role TEXT NOT NULL, url TEXT,
  status TEXT NOT NULL DEFAULT 'saved'
    CHECK (status IN ('saved','applied','interviewing','offer','closed')),
  deadline TEXT, applied_on TEXT,
  jd_text TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS reminder (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                -- post | deadline | follow_up | review
  ref_table TEXT, ref_id INTEGER,
  title TEXT NOT NULL,
  due_at TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0
);
"""

# Each migration runs after the previous version is applied.
# Append new entries; never edit ones already released.
MIGRATIONS: dict[int, str] = {
    # v2: keep FTS in sync automatically; capture bodies are never logged.
    2: """
    CREATE TRIGGER IF NOT EXISTS capture_fts_insert AFTER INSERT ON capture BEGIN
      INSERT INTO capture_fts(rowid, title, body)
      VALUES (new.id, coalesce(new.title, ''), new.body);
    END;
    CREATE TRIGGER IF NOT EXISTS capture_fts_delete AFTER DELETE ON capture BEGIN
      DELETE FROM capture_fts WHERE rowid = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS capture_fts_update AFTER UPDATE OF title, body ON capture BEGIN
      DELETE FROM capture_fts WHERE rowid = old.id;
      INSERT INTO capture_fts(rowid, title, body)
      VALUES (new.id, coalesce(new.title, ''), new.body);
    END;
    """,
    # v3: store generated job-tailoring artifacts (resume bullets, cover letters)
    # with the citations and warnings the verifier produced.
    3: """
    CREATE TABLE IF NOT EXISTS job_artifact (
      id INTEGER PRIMARY KEY,
      job_id INTEGER NOT NULL REFERENCES job(id),
      kind TEXT NOT NULL CHECK (kind IN ('bullets','cover')),
      body TEXT NOT NULL,
      citations TEXT,                  -- JSON: per-bullet cites / cover evidence ids
      warnings TEXT,                   -- JSON list from the citation verifier
      used_fallback INTEGER NOT NULL DEFAULT 0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """,
}


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with sane defaults (foreign keys, row access by name)."""
    path = Path(db_path) if db_path else DB_PATH
    if path != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations, oldest first."""
    version = current_version(conn)
    if version < 1:
        conn.executescript(INIT_SCHEMA)
        conn.execute("PRAGMA user_version = 1")
        version = 1
    for target in sorted(MIGRATIONS):
        if version < target:
            conn.executescript(MIGRATIONS[target])
            conn.execute(f"PRAGMA user_version = {target}")
            version = target
    conn.commit()


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create data dirs and return a migrated connection."""
    if db_path is None:
        ensure_dirs()
    conn = connect(db_path)
    migrate(conn)
    return conn


# --- small helpers used across modules -------------------------------------

def insert_capture(conn: sqlite3.Connection, cap: dict) -> int | None:
    """Insert a capture (FTS is synced by trigger). Returns id, or None if duplicate hash."""
    try:
        cur = conn.execute(
            """INSERT INTO capture
               (source, origin, title, body, content_hash, happened_at, project_id, tags)
               VALUES (:source, :origin, :title, :body, :content_hash, :happened_at,
                       :project_id, :tags)""",
            {
                "source": cap["source"],
                "origin": cap.get("origin"),
                "title": cap.get("title"),
                "body": cap["body"],
                "content_hash": cap.get("content_hash"),
                "happened_at": cap.get("happened_at"),
                "project_id": cap.get("project_id"),
                "tags": cap.get("tags"),
            },
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    conn.commit()
    return cur.lastrowid


def search_captures(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    """FTS search over captures, best match first."""
    rows = conn.execute(
        """SELECT c.* FROM capture c
           JOIN capture_fts f ON f.rowid = c.id
           WHERE capture_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (query, limit),
    ).fetchall()
    return list(rows)


def list_captures(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Most recent captures first (the inbox)."""
    rows = conn.execute(
        "SELECT * FROM capture ORDER BY captured_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return list(rows)


def list_origins(conn: sqlite3.Connection) -> list[str]:
    """Distinct origins seen so far, for origin tagging and filtering."""
    rows = conn.execute(
        "SELECT DISTINCT origin FROM capture WHERE origin IS NOT NULL ORDER BY origin"
    ).fetchall()
    return [r["origin"] for r in rows]


# --- journal helpers (M2) --------------------------------------------------

def captures_for_day(conn: sqlite3.Connection, day: str) -> list[dict]:
    """Captures whose work happened on the given yyyy-mm-dd."""
    rows = conn.execute(
        "SELECT * FROM capture WHERE happened_at LIKE ? ORDER BY id",
        (f"{day}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def captures_by_ids(conn: sqlite3.Connection, ids) -> dict[int, dict]:
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM capture WHERE id IN ({q})", ids).fetchall()
    return {r["id"]: dict(r) for r in rows}


def store_journal_entry(
    conn: sqlite3.Connection, day: str, kind: str, lines: list[dict]
) -> int:
    """Persist a journal entry and its cited lines. Returns entry id."""
    cur = conn.execute(
        "INSERT INTO journal_entry (day, kind) VALUES (?, ?)", (day, kind)
    )
    entry_id = cur.lastrowid
    for ln in lines:
        conn.execute(
            "INSERT INTO journal_line (entry_id, text, capture_ids) VALUES (?, ?, ?)",
            (entry_id, ln["text"], json.dumps(ln.get("cites", []))),
        )
    conn.commit()
    return entry_id


def list_journal_entries(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM journal_entry ORDER BY day DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def entry_lines(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM journal_line WHERE entry_id = ? ORDER BY id", (entry_id,)
    ).fetchall()
    return [
        {"id": r["id"], "text": r["text"], "capture_ids": json.loads(r["capture_ids"])}
        for r in rows
    ]


def daily_lines_between(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Daily journal lines in [start, end], with their entry day (for weekly digests)."""
    rows = conn.execute(
        """SELECT jl.id, jl.text, jl.capture_ids, je.day
           FROM journal_line jl
           JOIN journal_entry je ON je.id = jl.entry_id
           WHERE je.kind = 'daily' AND je.day >= ? AND je.day <= ?
           ORDER BY je.day, jl.id""",
        (start, end),
    ).fetchall()
    return [
        {"id": r["id"], "text": r["text"],
         "capture_ids": json.loads(r["capture_ids"]), "day": r["day"]}
        for r in rows
    ]


# --- posts (M4) -------------------------------------------------------------

def store_post(
    conn: sqlite3.Connection,
    workspace_id: int,
    body_md: str,
    *,
    title: str | None = None,
    status: str = "draft",
    source_ids=None,
    parent_post_id: int | None = None,
    warnings: list[str] | None = None,
) -> int:
    """Persist a draft/post. source_ids is stored as JSON; warnings too."""
    cur = conn.execute(
        "INSERT INTO post (workspace_id, title, body_md, status, source_ids, "
        "parent_post_id, warnings) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            workspace_id,
            title,
            body_md,
            status,
            json.dumps(source_ids) if source_ids is not None else None,
            parent_post_id,
            json.dumps(warnings) if warnings is not None else None,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_post(conn: sqlite3.Connection, post_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM post WHERE id = ?", (post_id,)).fetchone()
    return dict(row) if row else None


def list_posts(
    conn: sqlite3.Connection,
    workspace_id: int | None = None,
    status: str | None = None,
) -> list[dict]:
    q, params = "SELECT * FROM post", []
    clauses = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    rows = conn.execute(q + " ORDER BY id DESC", params).fetchall()
    return [dict(r) for r in rows]


def get_idea(conn: sqlite3.Connection, idea_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM idea WHERE id = ?", (idea_id,)).fetchone()
    return dict(row) if row else None


# --- projects (M6, context packs) -------------------------------------------

def get_or_create_project(conn: sqlite3.Connection, name: str) -> dict:
    """Projects are created on first mention so a context pack needs no setup."""
    name = name.strip()
    if not name:
        raise ValueError("project name is empty")
    row = conn.execute("SELECT * FROM project WHERE name = ?", (name,)).fetchone()
    if row is None:
        cur = conn.execute("INSERT INTO project (name) VALUES (?)", (name,))
        conn.commit()
        row = conn.execute("SELECT * FROM project WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM project ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def captures_for_project(conn: sqlite3.Connection, project_id: int, limit: int = 200) -> list[dict]:
    """Captures assigned to a project, newest first."""
    rows = conn.execute(
        "SELECT * FROM capture WHERE project_id = ? ORDER BY captured_at DESC, id DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def assign_capture_project(conn: sqlite3.Connection, capture_id: int, project_id: int) -> None:
    conn.execute("UPDATE capture SET project_id = ? WHERE id = ?", (project_id, capture_id))
    conn.commit()
