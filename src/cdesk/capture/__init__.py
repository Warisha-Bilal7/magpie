"""Capture sources: paste, files, git, chat_export, watcher."""

from .files import capture_file
from .git import add_git_captures, git_captures
from .paste import add_capture, capture_hash

__all__ = ["add_capture", "capture_hash", "capture_file",
           "git_captures", "add_git_captures"]
