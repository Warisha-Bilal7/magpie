"""Idea cards and duplicate detection (M6 #37, #38).

CRUD is plain SQLite. Duplicate detection is pure numpy over stored embeddings
with a tunable cosine threshold, so it is unit-tested with a fake embedder and
needs no model. See docs/PLAN.md F7.
"""

import json
import sqlite3
from typing import Callable

import numpy as np

STATUSES = ("spark", "researching", "building", "shipped", "parked")

# How similar two idea cards must be (cosine, 0-1) to count as near-duplicates.
# 0.82 was tuned on the author's own cards: catches rewrites of the same idea,
# misses two different ideas that merely share a project. Raise to 0.9 for
# stricter matching, lower to 0.75 for more suggestions.
DEFAULT_DUPLICATE_THRESHOLD = 0.82


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def _text(title: str, note: str | None) -> str:
    return f"{title}\n{note or ''}".strip()


# --- deterministic core (#38) ----------------------------------------------

def duplicates_for(
    vec: np.ndarray,
    rows: list[dict],
    threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
) -> list[dict]:
    """rows: [{"id", "title", "embedding" (bytes|np.ndarray)}]. Best match first.

    Only rows at or above the threshold are returned, so an empty list means
    "no near-duplicate" — the caller does not re-check the score.
    """
    from .voice import blob_to_vec

    out = []
    for r in rows:
        emb = r.get("embedding")
        if emb is None:
            continue
        other = emb if isinstance(emb, np.ndarray) else blob_to_vec(emb)
        score = _cosine(np.asarray(vec, dtype="float32"),
                        np.asarray(other, dtype="float32"))
        if score >= threshold and abs(score - 1.0) < 1e-6:
            # skip exact self-match for near-duplicate detection
            continue
        if score >= threshold:
            out.append({"id": r["id"], "title": r["title"], "score": score})
    return sorted(out, key=lambda m: -m["score"])


def find_duplicates(
    conn: sqlite3.Connection,
    title: str,
    note: str | None = None,
    threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    embedder: Callable[[list[str]], "object"] | None = None,
    exclude_id: int | None = None,
) -> list[dict]:
    """Idea cards near-duplicate to (title, note), best match first."""
    from .voice import embed_texts

    embedder = embedder or embed_texts
    rows = conn.execute(
        "SELECT id, title, embedding FROM idea WHERE embedding IS NOT NULL"
    ).fetchall()
    rows = [dict(r) for r in rows if r["id"] != exclude_id]
    if not rows:
        return []
    vec = np.asarray(embedder([_text(title, note)])[0], dtype="float32")
    return duplicates_for(vec, rows, threshold=threshold)


def index_idea(
    conn: sqlite3.Connection,
    idea_id: int,
    embedder: Callable[[list[str]], "object"] | None = None,
) -> bool:
    """Embed one idea's title+note and store it. False if the idea is missing."""
    from .voice import embed_texts, vec_to_blob

    idea = get_idea(conn, idea_id)
    if idea is None:
        return False
    embedder = embedder or embed_texts
    vec = np.asarray(embedder([_text(idea["title"], idea["note"])])[0], dtype="float32")
    conn.execute("UPDATE idea SET embedding = ? WHERE id = ?",
                 (vec_to_blob(vec), idea_id))
    conn.commit()
    return True


# --- CRUD (#37) -------------------------------------------------------------

def create_idea(
    conn: sqlite3.Connection,
    title: str,
    *,
    note: str | None = None,
    status: str = "spark",
    effort: int | None = None,
    impact: int | None = None,
    next_step: str | None = None,
    source_ids: list[int] | None = None,
    embedding: bytes | None = None,
) -> dict:
    if not title.strip():
        raise ValueError("idea title is empty")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    for name, value in (("effort", effort), ("impact", impact)):
        if value is not None and not 1 <= int(value) <= 5:
            raise ValueError(f"{name} must be 1-5")
    cur = conn.execute(
        """INSERT INTO idea (title, note, status, effort, impact, next_step,
                             source_ids, embedding)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title.strip(), note, status, effort, impact, next_step,
         json.dumps(source_ids) if source_ids is not None else None, embedding),
    )
    conn.commit()
    return get_idea(conn, cur.lastrowid)


def get_idea(conn: sqlite3.Connection, idea_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM idea WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        return None
    idea = dict(row)
    idea["source_ids"] = json.loads(idea["source_ids"]) if idea["source_ids"] else []
    return idea


def list_ideas(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    q, params = "SELECT * FROM idea", []
    if status is not None:
        q += " WHERE status = ?"
        params.append(status)
    rows = conn.execute(q + " ORDER BY updated_at DESC, id DESC", params).fetchall()
    out = []
    for r in rows:
        idea = dict(r)
        idea["source_ids"] = json.loads(idea["source_ids"]) if idea["source_ids"] else []
        out.append(idea)
    return out


def update_idea(conn: sqlite3.Connection, idea_id: int, **fields) -> dict:
    allowed = {"title", "note", "status", "effort", "impact", "next_step",
               "source_ids", "embedding"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}")
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if "source_ids" in fields and fields["source_ids"] is not None:
        fields["source_ids"] = json.dumps(fields["source_ids"])
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE idea SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [*fields.values(), idea_id],
        )
        conn.commit()
    return get_idea(conn, idea_id)


def delete_idea(conn: sqlite3.Connection, idea_id: int) -> None:
    conn.execute("DELETE FROM idea WHERE id = ?", (idea_id,))
    conn.commit()


def ideas_by_status(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Cards grouped into columns, highest impact/effort first — the board view."""
    board = {s: [] for s in STATUSES}
    for idea in list_ideas(conn):
        board[idea["status"]].append(idea)
    for cards in board.values():
        cards.sort(key=lambda i: (-(i["impact"] or 0), -(i["effort"] or 0), i["id"]))
    return board
