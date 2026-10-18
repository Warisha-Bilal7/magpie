"""Git capture: one note per repo per day, not per commit (#9)."""

import hashlib
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

from ..config import default_origin
from ..db import insert_capture


def git_captures(repo: str, since_iso: str) -> list[dict]:
    """One capture per repo per day, so a busy day is one note, not forty."""
    proc = subprocess.run(
        ["git", "-C", repo, "log", f"--since={since_iso}",
         "--pretty=format:%ad%x1f%s", "--date=short"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        if "does not have any commits" in proc.stderr or "your current branch" in proc.stderr:
            return []  # empty repo
        raise RuntimeError(f"git log failed: {proc.stderr.strip()}")
    out = proc.stdout
    by_day: dict[str, list[str]] = defaultdict(list)
    for row in out.splitlines():
        day, _, subject = row.partition("\x1f")
        if day:
            by_day[day].append(subject)
    caps = []
    for day in sorted(by_day):
        subjects = by_day[day]
        body = "\n".join(f"- {s}" for s in subjects)
        caps.append({
            "source": "git",
            "origin": str(Path(repo).resolve()),
            "title": f"Commits on {day}",
            "body": body,
            "happened_at": day,
            "content_hash": hashlib.sha256(f"{repo}|{day}|{body}".encode()).hexdigest(),
        })
    return caps


def add_git_captures(
    conn: sqlite3.Connection, repo: str, since_iso: str
) -> list[tuple[int | None, bool]]:
    """Insert a repo's per-day commit notes. Deduped by content hash."""
    results = []
    for cap in git_captures(repo, since_iso):
        if not cap.get("origin"):
            cap["origin"] = default_origin()
        rid = insert_capture(conn, cap)
        results.append((rid, rid is not None))
    return results
