"""Deterministic verification: citations, facts, platform rules.

The model writes; this module checks. Everything here is plain Python with
no model calls, unit-tested with planted errors (tests/test_verify.py).
Do not change a threshold or regex without updating its tests.
"""

import re


# ---------- journal: every line needs receipts ----------

def _contains_number(n: str, source: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(n)}(?!\d)", source) is not None


def unsupported_reasons(line: dict, by_id: dict[int, dict]) -> list[str]:
    """line = {"text": str, "cites": [int]}. by_id maps capture id to capture."""
    if not line["cites"]:
        return ["no citation"]
    cited = [by_id.get(c) for c in line["cites"]]
    if any(c is None for c in cited):
        return ["cites an unknown capture id"]
    source = " ".join(f"{c['title'] or ''} {c['body']}" for c in cited)
    reasons = []
    for n in re.findall(r"\d[\d,.]*\d|\d", line["text"]):
        n = n.rstrip(".,")
        if not _contains_number(n, source):
            reasons.append(f"number {n} not in cited captures")
    for u in re.findall(r"https?://\S+", line["text"]):
        if u.rstrip(".,)") not in source:
            reasons.append(f"url {u} not in cited captures")
    return reasons


# ---------- drafts: nothing invented ----------

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_DM = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS})[a-z]*\b", re.I)
_MD = re.compile(rf"\b({MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b", re.I)
_URL = re.compile(r"https?://[^\s)>\]]+", re.I)
_HANDLE = re.compile(r"@\w+")
_NUM = re.compile(r"(?<![\w:])\d{2,}(?![\w:])")


def extract_facts(text: str) -> set[str]:
    f: set[str] = set()
    for d, m in _DM.findall(text):
        f.add(f"date:{int(d)}-{m[:3].lower()}")
    for m, d in _MD.findall(text):
        f.add(f"date:{int(d)}-{m[:3].lower()}")
    for h, mi, ap in _TIME.findall(text):
        f.add(f"time:{int(h)}:{mi or '00'}{ap.lower()}")
    f |= {f"url:{u.rstrip('.,').lower()}" for u in _URL.findall(text)}
    f |= {f"handle:{h.lower()}" for h in _HANDLE.findall(text)}
    f |= {f"num:{n}" for n in _NUM.findall(text)}
    return f


def check_facts(draft: str, source: str) -> list[str]:
    """Every date, time, URL, handle and number in the draft must exist in the source."""
    missing = extract_facts(draft) - extract_facts(source)
    return [f"not in source: {x.split(':', 1)[1]}" for x in sorted(missing)]


def check_rules(draft: str, rules: dict) -> list[str]:
    v = []
    if len(draft) > rules.get("max_chars", 10**9):
        v.append(f"too long: {len(draft)} > {rules['max_chars']} characters")
    tags = re.findall(r"#\w+", draft)
    if len(tags) > rules.get("max_hashtags", 99):
        v.append(f"too many hashtags: {len(tags)} > {rules['max_hashtags']}")
    low = draft.lower()
    for phrase in rules.get("banned", []):
        if phrase.lower() in low:
            v.append(f"contains banned phrase: {phrase}")
    return v
