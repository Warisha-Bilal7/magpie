"""Workspaces, platform rules and the past-post voice corpus (M3).

One workspace per channel (Substack, LinkedIn, society, personal). Each has
a voice profile (past posts + embeddings), platform rules and a cadence
target. See docs/PLAN.md sections 5-6.
"""

import json
import sqlite3
from typing import Callable

from .config import DEFAULT_RULES, PLATFORM_RULES

KINDS = ("substack", "linkedin", "society", "personal", "other")


# --- workspace CRUD (#18) ---------------------------------------------------

def create_workspace(
    conn: sqlite3.Connection,
    name: str,
    *,
    kind: str,
    cadence_days: int | None = None,
    rules: dict | None = None,
    audience: str | None = None,
) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    rules_json = json.dumps(rules) if rules else None
    try:
        cur = conn.execute(
            "INSERT INTO workspace (name, kind, cadence_days, rules_json, audience) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, kind, cadence_days, rules_json, audience),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"workspace '{name}' already exists") from None
    conn.commit()
    return get_workspace(conn, cur.lastrowid)


def get_workspace(conn: sqlite3.Connection, ws_id: int | None = None,
                  name: str | None = None) -> dict | None:
    if ws_id is not None:
        row = conn.execute("SELECT * FROM workspace WHERE id = ?", (ws_id,)).fetchone()
    elif name is not None:
        row = conn.execute("SELECT * FROM workspace WHERE name = ?", (name,)).fetchone()
    else:
        raise ValueError("need ws_id or name")
    return dict(row) if row else None


def list_workspaces(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM workspace ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def update_workspace(conn: sqlite3.Connection, ws_id: int, **fields) -> dict:
    allowed = {"name", "kind", "cadence_days", "rules_json", "audience"}
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"cannot update {key}")
        sets.append(f"{key} = ?")
        values.append(value)
    if sets:
        values.append(ws_id)
        conn.execute(f"UPDATE workspace SET {', '.join(sets)} WHERE id = ?", values)
        conn.commit()
    return get_workspace(conn, ws_id)


def delete_workspace(conn: sqlite3.Connection, ws_id: int) -> None:
    conn.execute("DELETE FROM workspace WHERE id = ?", (ws_id,))
    conn.commit()


def effective_rules(ws: dict) -> dict:
    """Stored rules override platform defaults for the workspace kind."""
    rules = dict(DEFAULT_RULES)
    rules.update(PLATFORM_RULES.get(ws.get("kind") or "", {}))
    stored = json.loads(ws["rules_json"]) if ws.get("rules_json") else {}
    rules.update(stored)
    return rules


# --- banned phrases (#22) ---------------------------------------------------

def add_banned_phrase(conn: sqlite3.Connection, ws_id: int, phrase: str) -> dict:
    phrase = phrase.strip()
    if not phrase:
        raise ValueError("empty phrase")
    ws = get_workspace(conn, ws_id)
    if ws is None:
        raise ValueError("no such workspace")
    rules = json.loads(ws["rules_json"]) if ws["rules_json"] else {}
    banned = [p for p in rules.get("banned", []) if p.lower() != phrase.lower()]
    banned.append(phrase)
    rules["banned"] = banned
    return update_workspace(conn, ws_id, rules_json=json.dumps(rules))


def remove_banned_phrase(conn: sqlite3.Connection, ws_id: int, phrase: str) -> dict:
    ws = get_workspace(conn, ws_id)
    if ws is None:
        raise ValueError("no such workspace")
    rules = json.loads(ws["rules_json"]) if ws["rules_json"] else {}
    rules["banned"] = [p for p in rules.get("banned", []) if p.lower() != phrase.lower()]
    return update_workspace(conn, ws_id, rules_json=json.dumps(rules))


# --- past-post voice corpus (#19) -------------------------------------------

def add_past_post(
    conn: sqlite3.Connection,
    workspace_id: int,
    body: str,
    *,
    url: str | None = None,
    published_at: str | None = None,
) -> int:
    body = body.strip()
    if not body:
        raise ValueError("empty post body")
    cur = conn.execute(
        "INSERT INTO past_post (workspace_id, body, url, published_at) VALUES (?, ?, ?, ?)",
        (workspace_id, body, url, published_at),
    )
    conn.commit()
    return cur.lastrowid


def list_past_posts(conn: sqlite3.Connection, workspace_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, workspace_id, body, url, published_at, "
        "(embedding IS NOT NULL) AS indexed "
        "FROM past_post WHERE workspace_id = ? ORDER BY id",
        (workspace_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def index_workspace_embeddings(
    conn: sqlite3.Connection,
    workspace_id: int,
    embedder: Callable[[list[str]], "object"] | None = None,
) -> int:
    """Embed past posts that are not indexed yet. Returns how many were embedded."""
    from .voice import embed_texts, vec_to_blob

    embedder = embedder or embed_texts
    rows = conn.execute(
        "SELECT id, body FROM past_post WHERE workspace_id = ? AND embedding IS NULL",
        (workspace_id,),
    ).fetchall()
    if not rows:
        return 0
    vectors = embedder([r["body"] for r in rows])
    for row, vec in zip(rows, vectors):
        conn.execute(
            "UPDATE past_post SET embedding = ? WHERE id = ?",
            (vec_to_blob(vec), row["id"]),
        )
    conn.commit()
    return len(rows)


def parse_posts_text(text: str) -> list[dict]:
    """Past posts separated by a line containing only --- (BOM tolerated)."""
    text = text.lstrip("\ufeff")
    chunks = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            if buf and "".join(buf).strip():
                chunks.append({"body": "\n".join(buf).strip().lstrip("\ufeff")})
            buf = []
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        chunks.append({"body": "\n".join(buf).strip().lstrip("\ufeff")})
    return chunks


def parse_posts_json(text: str) -> list[dict]:
    """A JSON list of {body, url?, published_at?} (BOM tolerated)."""
    data = json.loads(text.lstrip("\ufeff"))
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of posts")
    out = []
    for item in data:
        if not isinstance(item, dict) or not str(item.get("body", "")).strip():
            raise ValueError("each post needs a non-empty body")
        out.append({
            "body": str(item["body"]).strip(),
            "url": item.get("url"),
            "published_at": item.get("published_at"),
        })
    return out


def import_posts(
    conn: sqlite3.Connection, workspace_id: int, posts: list[dict]
) -> list[int]:
    return [
        add_past_post(conn, workspace_id, p["body"], url=p.get("url"),
                      published_at=p.get("published_at"))
        for p in posts
    ]
