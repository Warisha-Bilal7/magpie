"""File-drop captures: markdown and text files (#7)."""

import sqlite3
from pathlib import Path

from .paste import add_capture

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def is_capturable(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TEXT_SUFFIXES


def capture_file(
    conn: sqlite3.Connection,
    path: Path | str,
    *,
    origin: str | None = None,
    happened_at: str | None = None,
) -> tuple[int | None, bool]:
    """Capture one markdown/text file. Title comes from the filename.

    Returns (id, created); created is False on content-hash dedupe, so
    re-dropping the same file is a no-op.
    """
    p = Path(path)
    if not is_capturable(p):
        raise ValueError(f"not a capturable text file: {p.name}")
    body = p.read_text(encoding="utf-8", errors="replace")
    return add_capture(
        conn,
        body,
        source="file",
        origin=origin,
        title=p.stem.replace("_", " ").replace("-", " "),
        happened_at=happened_at,
        tags=p.suffix.lstrip("."),
    )
