"""Capture adapter for Antigravity chat transcripts.

Reads transcript.jsonl from Antigravity conversation sessions, extracts the
author's prompts, technical problems, architectural decisions, and agent
summaries, and imports them into Content Desk's capture inbox.
"""

import json
import os
import re
from pathlib import Path
import sqlite3
from typing import Sequence

from .paste import add_capture


def clean_prompt_text(text: str) -> str:
    """Strip XML wrapper tags like <USER_REQUEST> from Antigravity user input."""
    if not text:
        return ""
    # Strip <USER_REQUEST>...</USER_REQUEST> tags if present
    text = re.sub(r"<\/?USER_REQUEST>", "", text)
    # Strip <ADDITIONAL_METADATA>...</ADDITIONAL_METADATA>
    text = re.sub(r"<ADDITIONAL_METADATA>[\s\S]*?<\/ADDITIONAL_METADATA>", "", text)
    # Strip system messages
    text = re.sub(r"<SYSTEM_MESSAGE>[\s\S]*?<\/SYSTEM_MESSAGE>", "", text)
    return text.strip()


def parse_transcript_text(jsonl_content: str, conv_id: str = "session") -> dict | None:
    """Parse JSONL lines into a structured capture dict {title, body, happened_at, origin}."""
    lines = [line.strip() for line in jsonl_content.splitlines() if line.strip()]
    if not lines:
        return None

    turns = []
    happened_at = None
    first_user_goal = None

    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        step_type = data.get("type")
        created_at = data.get("created_at")
        if created_at and not happened_at:
            happened_at = created_at.split("T")[0]

        if step_type == "USER_INPUT":
            raw_content = str(data.get("content", ""))
            cleaned = clean_prompt_text(raw_content)
            if cleaned and len(cleaned) > 10:
                if not first_user_goal:
                    # Grab first line of first real user goal as title candidate
                    first_line = cleaned.split("\n")[0].strip("# \t-")
                    first_user_goal = first_line[:90]
                turns.append(f"User: {cleaned}")
        elif step_type == "PLANNER_RESPONSE":
            content = str(data.get("content", "")).strip()
            # Only record substantial text responses, not empty tool triggers
            if content and len(content) > 30 and not content.startswith("<thinking>"):
                # Truncate overly verbose responses to keep capture punchy
                if len(content) > 1500:
                    content = content[:1500] + "... [truncated]"
                turns.append(f"Assistant: {content}")

    if not turns:
        return None

    title = first_user_goal or f"Antigravity chat {conv_id}"
    body = "\n\n".join(turns)

    return {
        "title": title,
        "body": body,
        "happened_at": happened_at,
        "origin": f"antigravity:{conv_id}",
    }


def parse_transcript_file(path: Path | str) -> dict | None:
    """Parse an Antigravity transcript.jsonl file on disk."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    # Derive conversation id from parent directory if standard layout
    conv_id = p.parent.parent.name if p.parent.name == "logs" else p.stem
    return parse_transcript_text(raw, conv_id=conv_id)


def import_antigravity_session(
    conn: sqlite3.Connection,
    content_or_path: str | Path,
    conv_id: str | None = None,
) -> tuple[int | None, bool]:
    """Import a single conversation transcript into the capture inbox."""
    if isinstance(content_or_path, Path) or (isinstance(content_or_path, str) and os.path.exists(content_or_path)):
        p = Path(content_or_path)
        conv = parse_transcript_file(p)
    else:
        conv = parse_transcript_text(str(content_or_path), conv_id=conv_id or "session")

    if not conv:
        return None, False

    cap_id, created = add_capture(
        conn,
        conv["body"],
        source="chat_export",
        origin=conv["origin"],
        title=conv["title"],
        happened_at=conv["happened_at"],
    )
    return cap_id, created


def scan_and_import_brain(
    conn: sqlite3.Connection,
    brain_dir: str | Path | None = None,
    limit: int = 15,
) -> list[tuple[int | None, bool, str]]:
    """Scan Antigravity brain directory and import all recent conversation transcripts."""
    if brain_dir is None:
        brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    else:
        brain_dir = Path(brain_dir)

    if not brain_dir.exists():
        return []

    results = []
    subdirs = sorted(
        [d for d in brain_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    for conv_folder in subdirs[:limit]:
        transcript_path = conv_folder / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript_path.exists():
            continue
        try:
            conv = parse_transcript_file(transcript_path)
            if not conv:
                continue
            cap_id, created = add_capture(
                conn,
                conv["body"],
                source="chat_export",
                origin=conv["origin"],
                title=conv["title"],
                happened_at=conv["happened_at"],
            )
            results.append((cap_id, created, conv["title"]))
        except Exception:
            continue

    return results
