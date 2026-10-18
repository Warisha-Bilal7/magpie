"""Optional drop-folder watcher (#7).

Watches config.DROP_DIR for new markdown/text files and captures them.
Run with `cdesk watch`. Ctrl-C to stop. The same capture_file function is
used for one-off drops, so tests do not need a live observer.
"""

import sqlite3
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..config import DROP_DIR, default_origin, ensure_dirs
from .files import capture_file, is_capturable


class DropHandler(FileSystemEventHandler):
    def __init__(self, conn: sqlite3.Connection, origin: str | None = None):
        super().__init__()
        self.conn = conn
        self.origin = origin if origin is not None else default_origin()

    def handle_path(self, path: Path) -> tuple[int | None, bool] | None:
        """Capture one file if it is markdown/text and non-empty.

        Editors save via temp-file rename, so the file may not exist yet on
        the first event; swallow races and let the next event retry.
        """
        p = Path(path)
        if not is_capturable(p):
            return None
        try:
            if not p.read_text(encoding="utf-8", errors="replace").strip():
                return None
            return capture_file(self.conn, p, origin=self.origin)
        except OSError:
            return None

    def on_created(self, event):
        if not event.is_directory:
            self.handle_path(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.handle_path(event.dest_path)


def start_watcher(conn: sqlite3.Connection, origin: str | None = None,
                  directory: Path | str | None = None) -> Observer:
    """Start a background observer on the drop folder. Caller stops it."""
    ensure_dirs()
    folder = Path(directory) if directory else DROP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(DropHandler(conn, origin), str(folder), recursive=False)
    observer.start()
    return observer
