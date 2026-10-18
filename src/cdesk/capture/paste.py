"""Paste and quick-add captures, with content-hash dedupe (#6)."""

import hashlib
import sqlite3
from datetime import datetime, timezone

from ..config import default_origin
from ..db import insert_capture


def capture_hash(body: str) -> str:
    """sha256 of the body — the dedupe key. Whitespace is significant."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def add_capture(
    conn: sqlite3.Connection,
    body: str,
    *,
    source: str = "paste",
    origin: str | None = None,
    title: str | None = None,
    happened_at: str | None = None,
    project_id: int | None = None,
    tags: str | None = None,
) -> tuple[int | None, bool]:
    """Store a capture. Returns (id, created).

    id is None and created is False when the exact body already exists
    (same content hash) — that is the dedupe contract for every source.
    """
    body = body.strip()
    if not body:
        raise ValueError("capture body is empty")
    cap = {
        "source": source,
        "origin": origin if origin is not None else default_origin(),
        "title": title,
        "body": body,
        "content_hash": capture_hash(body),
        "happened_at": happened_at or datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "tags": tags,
    }
    rowid = insert_capture(conn, cap)
    return rowid, rowid is not None
