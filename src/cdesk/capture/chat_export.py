"""Chat-export parser (#8).

Formats drift, so parse what we recognise and fall back to a plain paste:
- ChatGPT export: conversations.json with a "mapping" of messages
- Generic JSON: {"title": ..., "messages": [{"role", "content"}]}
  (or a bare list of such dicts)
- Markdown transcripts with alternating "## Human" / "## Assistant" sections

Anything else becomes one capture of the raw text (the paste fallback).
"""

import json
import sqlite3
from pathlib import Path

from .paste import add_capture


def _chatgpt_conversations(data: list) -> list[dict]:
    out = []
    for conv in data:
        title = conv.get("title") or "ChatGPT conversation"
        parts = []
        mapping = conv.get("mapping") or {}
        for node in mapping.values():
            message = node.get("message") if isinstance(node, dict) else None
            if not message:
                continue
            content = message.get("content") or {}
            text = content.get("parts") or []
            role = message.get("role", "")
            joined = "\n".join(t for t in text if isinstance(t, str)).strip()
            if joined:
                parts.append(f"{role}: {joined}")
        if parts:
            out.append({"title": title, "body": "\n\n".join(parts)})
    return out


def _generic_messages(data) -> list[dict]:
    if isinstance(data, dict):
        convs = [data]
    else:
        convs = list(data)
    out = []
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        title = conv.get("title") or "Chat export"
        messages = conv.get("messages") or []
        parts = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):  # some exports use content blocks
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            if content:
                parts.append(f"{role}: {content}".strip())
        if parts:
            out.append({"title": title, "body": "\n\n".join(parts)})
    return out


def _markdown_sections(text: str) -> list[dict]:
    """Split a markdown transcript on '## Human' / '## Assistant' headers."""
    lines = text.splitlines()
    sections: list[dict] = []
    current_role: str | None = None
    buf: list[str] = []
    for line in lines:
        header = line.strip().lstrip("#").strip().lower()
        if header in ("human", "assistant", "user", "ai"):
            if current_role and buf:
                sections.append({"role": current_role, "body": "\n".join(buf).strip()})
            current_role = header
            buf = []
        elif current_role is not None:
            buf.append(line)
    if current_role and buf:
        sections.append({"role": current_role, "body": "\n".join(buf).strip()})
    sections = [s for s in sections if s["body"]]
    if not sections:
        return []
    return [{"title": "Chat transcript", "body": "\n\n".join(f"{s['role']}: {s['body']}" for s in sections)}]


def parse_export(path: Path | str) -> list[dict]:
    """Parse a chat export file into capture dicts (title/body, no ids)."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            if isinstance(data, list) and data and isinstance(data[0], dict) and "mapping" in data[0]:
                parsed = _chatgpt_conversations(data)
            else:
                parsed = _generic_messages(data)
            if parsed:
                return parsed
    md = _markdown_sections(raw)
    if md:
        return md
    # paste fallback: the raw text is still worth capturing
    return [{"title": p.stem, "body": raw.strip()}]


def add_chat_export(
    conn: sqlite3.Connection, path: Path | str, *, origin: str | None = None
) -> list[tuple[int | None, bool]]:
    """Parse a chat export and store each conversation as a capture."""
    results = []
    for conv in parse_export(path):
        rid, created = add_capture(
            conn, conv["body"], source="chat_export", origin=origin, title=conv["title"]
        )
        results.append((rid, created))
    return results
