"""Automated writing style analyzer and voice profiler.

Analyzes published past posts to automatically extract style metrics, sentence
cadence, rhetorical patterns, and unmasks AI clichés to ban, updating the
workspace rules without needing manual prompt configuration.
"""

import json
import math
import re
import sqlite3
from typing import Sequence

# Known generic AI clichés and corporate filler phrases
COMMON_AI_TROPES = [
    "delve",
    "delving",
    "testament to",
    "tapestry",
    "beacon",
    "game-changer",
    "game changer",
    "pivotal",
    "revolutionize",
    "seamlessly",
    "harness the",
    "harnessing",
    "supercharge",
    "in today's fast-paced world",
    "in an era of",
    "it's important to remember",
    "at the end of the day",
    "furthermore",
    "moreover",
    "in conclusion",
    "dive deep",
    "thrilled to announce",
    "excited to share",
    "groundbreaking",
]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, ignoring abbreviations."""
    # Simple regex for sentence splitting
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = []
    for s in sentences:
        s = s.strip()
        if len(s) > 3:
            cleaned.append(s)
    return cleaned


def detect_unwanted_ai_tropes(texts: Sequence[str]) -> list[str]:
    """Identify AI buzzwords that the author NEVER uses, so they can be explicitly banned."""
    corpus = " ".join(texts).lower()
    banned = []
    for trope in COMMON_AI_TROPES:
        if trope.lower() not in corpus:
            banned.append(trope)
    return banned


def analyze_writing_style(texts: Sequence[str]) -> dict:
    """Analyze a corpus of posts and generate a rich style and cadence profile."""
    if not texts:
        return {
            "avg_sentence_len": 15.0,
            "avg_para_len": 2.5,
            "banned_ai_tropes": COMMON_AI_TROPES,
            "cadence_notes": "Balanced paragraph and sentence flow.",
            "voice_summary": "Direct, authentic technical voice.",
            "tone_notes": "Clear, grounded and objective.",
        }

    total_words = 0
    all_sentence_lengths = []
    total_paragraphs = 0
    total_questions = 0
    first_person_count = 0
    headings_count = 0

    first_person_re = re.compile(r"\b(i|me|my|mine|myself|we|us|our|ours)\b", re.I)
    question_re = re.compile(r"\?")
    heading_re = re.compile(r"^#+\s+.+", re.M)

    for doc in texts:
        # Headings
        headings = heading_re.findall(doc)
        headings_count += len(headings)

        # Questions
        questions = question_re.findall(doc)
        total_questions += len(questions)

        # Paragraphs
        paras = [p.strip() for p in doc.split("\n\n") if p.strip()]
        total_paragraphs += len(paras)

        # Words & First person
        words = re.findall(r"\b\w+\b", doc)
        total_words += len(words)
        first_person_count += len(first_person_re.findall(doc))

        # Sentences
        sentences = split_sentences(doc)
        for s in sentences:
            s_words = len(re.findall(r"\b\w+\b", s))
            if s_words > 0:
                all_sentence_lengths.append(s_words)

    n_sentences = max(len(all_sentence_lengths), 1)
    avg_sentence_len = sum(all_sentence_lengths) / n_sentences

    variance = sum((x - avg_sentence_len) ** 2 for x in all_sentence_lengths) / n_sentences
    sentence_std = math.sqrt(variance)

    n_paras = max(total_paragraphs, 1)
    avg_para_len = n_sentences / n_paras

    # Determine rhythm description
    if sentence_std > 8.0:
        cadence_notes = "Dynamic cadence: strong mix of short punchy statements with longer explanatory sentences."
    elif avg_sentence_len < 12.0:
        cadence_notes = "Crisp, concise rhythm: tight sentences with rapid progression."
    else:
        cadence_notes = "Measured and narrative cadence: steady flow with thorough development."

    # First-person orientation
    is_personal_narrative = (first_person_count / max(total_words, 1)) > 0.015

    tone_aspects = []
    if is_personal_narrative:
        tone_aspects.append("First-person builder perspective; candid and grounded in direct experience")
    else:
        tone_aspects.append("Analytical and problem-focused")

    if total_questions / max(len(texts), 1) >= 1.0:
        tone_aspects.append("Uses probing rhetorical questions to draw readers into technical dilemmas")

    tone_aspects.append("Concrete technical receipts over theoretical abstractions")

    tone_notes = "; ".join(tone_aspects) + "."

    # AI tropes to ban
    banned_tropes = detect_unwanted_ai_tropes(texts)

    voice_summary = (
        f"Author's voice: {tone_notes} "
        f"Sentence length averages {avg_sentence_len:.1f} words. {cadence_notes} "
        f"Paragraphs are typically {avg_para_len:.1f} sentences. Never use generic AI fluff."
    )

    return {
        "avg_sentence_len": round(avg_sentence_len, 1),
        "sentence_len_std": round(sentence_std, 1),
        "avg_para_len": round(avg_para_len, 1),
        "first_person_ratio": round(first_person_count / max(total_words, 1), 3),
        "cadence_notes": cadence_notes,
        "tone_notes": tone_notes,
        "voice_summary": voice_summary,
        "banned_ai_tropes": banned_tropes,
    }


def apply_style_to_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    style_profile: dict,
) -> dict:
    """Save the derived style profile and banned tropes directly into workspace.rules_json."""
    from .workspaces import get_workspace, update_workspace

    ws = get_workspace(conn, workspace_id)
    if ws is None:
        raise ValueError(f"no workspace with id {workspace_id}")

    rules = json.loads(ws["rules_json"]) if ws.get("rules_json") else {}

    # Merge banned tropes
    current_banned = set(rules.get("banned", []))
    for trope in style_profile.get("banned_ai_tropes", []):
        current_banned.add(trope.lower())
    rules["banned"] = sorted(list(current_banned))

    # Add tone and cadence notes
    rules["tone_notes"] = style_profile.get("tone_notes", "")
    rules["cadence_notes"] = style_profile.get("cadence_notes", "")
    rules["voice_summary"] = style_profile.get("voice_summary", "")

    return update_workspace(conn, workspace_id, rules_json=json.dumps(rules))
