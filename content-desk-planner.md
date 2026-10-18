# Content Desk

> A local-first work journal and posting desk. It captures work scattered across AI chats, notes and git repos, turns it into a source-linked journal, and drafts posts for Substack, LinkedIn and society channels in your own voice. It also keeps a planner with posting nudges, a project-ideas organizer, and a job-application tracker whose resume bullets come from real journal entries. A local open-weight model writes; deterministic code verifies, schedules and counts. Nothing leaves the machine.

---

## 1. Design principles

1. **The journal is the center; posts are by-products.** Most "caption writers" start from a blank box. Content Desk starts from work you actually did, so there is always something true to post about.
2. **Facts in, prose out, with receipts.** The model only sees captured material. Every journal line carries citations to the captures it came from, and every draft is checked against its source for invented dates, links, numbers and handles.
3. **The model writes. Code verifies and schedules.** Citation checks, fact checks, platform rules, nudges, reminders and calendar export are plain Python and unit-tested.
4. **Capture must be effortless or it will not happen.** Paste, drop a file, one CLI command, or a git scan. The tool must be easier than leaving the note in whatever chat it started in.
5. **Model-agnostic by design.** You work across several AI accounts. Content Desk sits above them as a neutral, local layer, and its own model can be swapped in one config line.
6. **Runs on a student laptop.** Small 4-bit models, one loaded at a time, a template fallback when no model is available, everything stored in SQLite and markdown.
7. **Open end to end.** Ollama or llama.cpp, an open-weight model, a local embedding model, SQLite, LangGraph, Streamlit, and `.ics` for calendars.

## 2. Features

| # | Module | What it does |
|---|---|---|
| F1 | Capture inbox | Paste text, drop files (markdown, text, JSON chat exports), scan git repos, quick-add from the CLI. Tag each capture with its origin (for example "claude-acct-2", "gemini", "opencode", a repo path) |
| F2 | Work journal | Daily and weekly entries drafted from captures. Every line cites its captures. Searchable by keyword and by meaning |
| F3 | Workspaces | One per channel: Substack, LinkedIn, your society, personal. Each has a voice profile, platform rules, audience notes, cadence target and its own calendar |
| F4 | Drafting pipeline | Source (journal lines, an existing post, or an idea) to draft in the workspace's voice, then fact-check, platform-rules check, retry, save |
| F5 | Repurposing | One post or journal entry becomes drafts for the other workspaces |
| F6 | Planner | Week and month view, posting slots, deadlines, reminders, "you have not posted in N days" nudges, `.ics` export for Google Calendar |
| F7 | Ideas organizer | Idea cards with status, effort, impact, next step, links to source captures, and near-duplicate detection |
| F8 | Context packs | Generate a compact markdown brief of a project (recent journal lines, decisions, open questions) to paste into any AI account, so scattered chats share context |
| F9 | Job tracker | Kanban (saved, applied, interviewing, offer, closed), deadlines, follow-up reminders |
| F10 | Job tailoring | Match a job description to your journal evidence, then draft resume bullets and a cover letter grounded in cited entries |
| F11 | Weekly review | One page: what you shipped, what you posted, what is overdue, which idea to pick next, which applications need follow-up |

## 3. Pipelines

Three LangGraph graphs use the model. Everything else is services and plain functions.

**Journal graph** (F2)

```
select -> summarize (LLM) -> verify --pass--> store -> END
              ^                 |
              +-- unsupported --+   (retry with feedback, max 2; still-bad lines are dropped and warned)
```

**Draft graph** (F4, F5)

```
gather -> voice -> write (LLM) -> fact_check -> rules_check --pass--> save -> END
                      ^                              |
                      +------ violations ------------+   (feed exact violations back, max 2)
                                                     +--- attempts exhausted --> save with warnings
```

**Job tailor graph** (F10)

```
parse_jd (LLM) -> match_evidence -> write_bullets (LLM) -> verify (same citation check) -> store -> END
```

| Node | Model? | Job |
|---|---|---|
| select | no | Pick captures for a day or week, trim long bodies |
| summarize | yes (structured output) | Return `lines: [{text, cites}]`, one concrete item per line |
| verify | no | Every line has citations; numbers, dates and URLs must appear in the cited captures |
| gather | no | Assemble the allowed facts for a draft (journal lines, source post, idea, brief) |
| voice | no (embeddings) | Retrieve the 3 most similar past posts from the workspace as style examples |
| write | yes | Draft the post using only the facts, in the voice shown, with the platform rules |
| fact_check | no | Extract dates, times, URLs, handles and numbers from the draft; each must exist in the source |
| rules_check | no | Length, hashtags, banned phrases from the workspace rules |
| parse_jd | yes (structured output) | Job description to a list of requirements |
| match_evidence | no (embeddings) | Find journal lines that support each requirement |
| write_bullets | yes | Bullets using only matched lines, with citations |

**Template fallback.** If Ollama is unreachable or a model errors, the journal falls back to a deterministic digest (captures grouped by origin), and drafts fall back to a fixed template filled from the facts. The app always produces something, and the fallback is the baseline for the model comparison.

## 4. Repo layout

```
content-desk/
├── README.md
├── AGENTS.md               # rules for opencode (section 11)
├── pyproject.toml
├── docs/PLAN.md            # this file
├── src/cdesk/
│   ├── config.py           # paths, model names, platform rules (section 6)
│   ├── db.py               # schema and helpers (section 5)
│   ├── llm.py              # Ollama chat and embed, fallback handling
│   ├── verify.py           # citation check, fact check, rules check (section 7)
│   ├── voice.py            # embeddings and nearest past posts
│   ├── planner.py          # nudges, reminders, ics export
│   ├── ideas.py            # idea cards, duplicate detection
│   ├── jobs.py             # kanban, deadlines, tailoring helpers
│   ├── context_pack.py     # F8
│   ├── capture/
│   │   ├── paste.py
│   │   ├── files.py
│   │   ├── git.py
│   │   ├── chat_export.py
│   │   └── watcher.py      # optional: watch a drop folder
│   ├── graphs/
│   │   ├── journal.py
│   │   ├── draft.py
│   │   └── job_tailor.py
│   ├── prompts/            # journal.txt, draft.txt, jd.txt, bullets.txt
│   ├── cli.py              # typer: add, journal, draft, nudge, ics, context
│   └── app/
│       ├── Home.py         # weekly review and nudges
│       └── pages/          # 1_Inbox, 2_Journal, 3_Workspaces, 4_Planner, 5_Ideas, 6_Jobs
├── data/                   # SQLite, drop folder, exports (gitignored)
├── eval/
│   ├── fixtures/           # sample captures, planted-error drafts
│   ├── run_eval.py
│   ├── models.yaml
│   └── results.csv
└── tests/
```

Dependencies: `langgraph ollama pydantic typer streamlit numpy pandas jinja2 psutil watchdog` (dev: `pytest`).

---

## 5. Data model

```sql
-- src/cdesk/db.py
CREATE TABLE workspace (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('substack','linkedin','society','personal','other')),
  cadence_days INTEGER,              -- target: post every N days
  rules_json TEXT,                   -- max_chars, max_hashtags, banned phrases, tone notes
  audience TEXT
);

CREATE TABLE project (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  note TEXT
);

CREATE TABLE capture (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,              -- paste | file | git | chat_export | quick
  origin TEXT,                       -- e.g. "claude-acct-2", "gemini", "opencode", repo path
  title TEXT,
  body TEXT NOT NULL,
  content_hash TEXT UNIQUE,          -- sha256 of body, for dedupe
  happened_at TEXT,                  -- when the work happened (ISO)
  captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
  project_id INTEGER REFERENCES project(id),
  tags TEXT
);
CREATE VIRTUAL TABLE capture_fts USING fts5(title, body);   -- insert with rowid = capture.id

CREATE TABLE journal_entry (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,                 -- yyyy-mm-dd (week start for weekly entries)
  kind TEXT NOT NULL CHECK (kind IN ('daily','weekly')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE journal_line (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES journal_entry(id),
  text TEXT NOT NULL,
  capture_ids TEXT NOT NULL,         -- JSON list of capture ids (the receipts)
  embedding BLOB
);

CREATE TABLE post (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  title TEXT,
  body_md TEXT,
  status TEXT NOT NULL DEFAULT 'idea'
    CHECK (status IN ('idea','draft','approved','scheduled','published')),
  scheduled_at TEXT,
  published_at TEXT,
  source_ids TEXT,                   -- JSON: journal line ids / capture ids used
  parent_post_id INTEGER REFERENCES post(id),   -- repurposed from
  warnings TEXT                      -- JSON list from fact/rules checks
);

CREATE TABLE past_post (             -- voice corpus: your real published posts
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  body TEXT NOT NULL,
  url TEXT,
  published_at TEXT,
  embedding BLOB
);

CREATE TABLE idea (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'spark'
    CHECK (status IN ('spark','researching','building','shipped','parked')),
  effort INTEGER, impact INTEGER,    -- 1-5
  next_step TEXT,
  source_ids TEXT,                   -- JSON capture ids
  embedding BLOB,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE job (
  id INTEGER PRIMARY KEY,
  company TEXT NOT NULL, role TEXT NOT NULL, url TEXT,
  status TEXT NOT NULL DEFAULT 'saved'
    CHECK (status IN ('saved','applied','interviewing','offer','closed')),
  deadline TEXT, applied_on TEXT,
  jd_text TEXT, notes TEXT
);

CREATE TABLE reminder (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                -- post | deadline | follow_up | review
  ref_table TEXT, ref_id INTEGER,
  title TEXT NOT NULL,
  due_at TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0
);
```

Everything lives in one SQLite file under `data/`. Back it up by copying the file. Never commit `data/`.

---

## 6. State definitions and config

```python
# src/cdesk/graphs/journal.py
import operator
from typing import Annotated, TypedDict
from pydantic import BaseModel


class JournalLine(BaseModel):            # structured output from the model
    text: str
    cites: list[int]                     # capture ids

class JournalLines(BaseModel):
    lines: list[JournalLine]

class JournalState(TypedDict, total=False):
    day: str                             # yyyy-mm-dd
    kind: str                            # daily | weekly
    model_name: str
    captures: list[dict]                 # id, origin, title, body (trimmed), happened_at
    lines: list[dict]                    # {"text", "cites"}
    bad: dict[int, list[str]]            # line index -> reasons
    attempt: int
    entry_id: int
    used_fallback: bool
    warnings: Annotated[list[str], operator.add]
```

```python
# src/cdesk/graphs/draft.py
import operator
from typing import Annotated, Literal, TypedDict

class DraftState(TypedDict, total=False):
    workspace_id: int
    source_kind: Literal["journal", "post", "idea", "freeform"]
    source_ids: list[int]
    brief: str                           # optional: "announce the workshop on 4 Nov"
    model_name: str
    source_text: str                     # the ONLY facts the draft may use
    voice_examples: list[str]
    rules: dict
    draft: str
    violations: list[str]
    attempt: int
    used_fallback: bool
    post_id: int
    warnings: Annotated[list[str], operator.add]
```

```python
# src/cdesk/config.py
MODEL_NAME = "qwen2.5:3b"                # swap in one line; see section 8
EMBED_MODEL = "nomic-embed-text"

# Starting values. VERIFY current platform limits before relying on them.
PLATFORM_RULES = {
    "linkedin":  {"max_chars": 3000, "max_hashtags": 5,
                  "banned": ["i'm thrilled", "excited to announce", "game-changer"]},
    "substack":  {"max_chars": 100_000, "max_hashtags": 0, "banned": []},
    "society":   {"max_chars": 2200, "max_hashtags": 8, "banned": []},   # e.g. Instagram caption
    "personal":  {"max_chars": 100_000, "max_hashtags": 5, "banned": []},
}
MAX_ATTEMPTS = 2
```

Banned phrases are the cheapest style lint. Grow the list from phrases you delete from drafts by hand.

---

## 7. Verification, capture, voice and planning logic

All plain Python, testable without a model. This is the core of the project.

```python
# src/cdesk/verify.py
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
```

**Capture: git**

```python
# src/cdesk/capture/git.py
import hashlib, subprocess
from collections import defaultdict

def git_captures(repo: str, since_iso: str) -> list[dict]:
    """One capture per repo per day, so a busy day is one note, not forty."""
    out = subprocess.run(
        ["git", "-C", repo, "log", f"--since={since_iso}",
         "--pretty=format:%ad%x1f%s", "--date=short"],
        capture_output=True, text=True, check=True,
    ).stdout
    by_day = defaultdict(list)
    for row in out.splitlines():
        day, _, subject = row.partition("\x1f")
        by_day[day].append(subject)
    caps = []
    for day, subjects in by_day.items():
        body = "\n".join(f"- {s}" for s in subjects)
        caps.append({
            "source": "git", "origin": repo, "title": f"Commits on {day}",
            "body": body, "happened_at": day,
            "content_hash": hashlib.sha256(f"{repo}|{day}|{body}".encode()).hexdigest(),
        })
    return caps
```

**Voice retrieval (embeddings)**

```python
# src/cdesk/voice.py
import numpy as np, ollama
from .config import EMBED_MODEL

def embed(texts: list[str]) -> np.ndarray:
    # Check your ollama-python version: older releases use ollama.embeddings(...) instead.
    r = ollama.embed(model=EMBED_MODEL, input=texts)
    return np.array(r["embeddings"], dtype="float32")

def top_k(query_vec: np.ndarray, mat: np.ndarray, k: int = 3) -> list[int]:
    sims = (mat @ query_vec) / (np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec) + 1e-9)
    return list(np.argsort(-sims)[:k])
```

Store embeddings as `np.float32` bytes in the BLOB columns (`arr.tobytes()` and `np.frombuffer(b, dtype="float32")`). The same helpers power journal search, idea duplicate detection (flag pairs above a cosine threshold such as 0.85, tuned on your own ideas) and job-to-evidence matching.

**Planner: nudges and calendar export**

```python
# src/cdesk/planner.py
from datetime import date, datetime, timedelta, timezone

def due_nudges(workspaces: list[dict], last_post: dict[int, date], today: date) -> list[dict]:
    """Workspaces that have gone quiet for longer than their cadence target."""
    out = []
    for w in workspaces:
        if not w.get("cadence_days"):
            continue
        last = last_post.get(w["id"])
        gap = (today - last).days if last else None
        if gap is None or gap >= w["cadence_days"]:
            out.append({"workspace": w["name"], "days_since": gap,
                        "overdue_by": None if gap is None else gap - w["cadence_days"]})
    return out


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def to_ics(events: list[dict]) -> str:
    """events: [{"uid": str, "title": str, "start": aware datetime, "minutes": int}]"""
    now = datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//content-desk//EN"]
    for e in events:
        end = e["start"] + timedelta(minutes=e.get("minutes", 30))
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}@content-desk", f"DTSTAMP:{_fmt(now)}",
                  f"DTSTART:{_fmt(e['start'])}", f"DTEND:{_fmt(end)}",
                  f"SUMMARY:{_esc(e['title'])}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
```

Nudge text ("9 days since your last Substack post") is a template. The optional "here are 3 drafts from this week" runs the draft graph on that week's journal lines.

**Context packs (F8)**: `context_pack.py` assembles a project brief in markdown (recent approved journal lines with dates, decisions, open questions, linked idea cards) so you can paste it at the top of a new chat in any AI account. It is deterministic, so no model is needed.

---

## 8. Node and edge wiring

```python
# src/cdesk/graphs/draft.py (wiring)
from typing import Literal
from langgraph.graph import StateGraph, START, END
from ..config import MAX_ATTEMPTS

def draft_router(state: DraftState) -> Literal["write", "save"]:
    if not state.get("violations"):
        return "save"
    if state["attempt"] >= MAX_ATTEMPTS:
        return "save"                    # saved with warnings so the human sees them
    return "write"

def build_draft_graph():
    g = StateGraph(DraftState)
    for name, fn in [("gather", gather), ("voice", voice), ("write", write),
                     ("fact_check", fact_check), ("rules_check", rules_check), ("save", save)]:
        g.add_node(name, fn)
    g.add_edge(START, "gather")
    g.add_edge("gather", "voice")
    g.add_edge("voice", "write")
    g.add_edge("write", "fact_check")
    g.add_edge("fact_check", "rules_check")
    g.add_conditional_edges("rules_check", draft_router, {"write": "write", "save": "save"})
    g.add_edge("save", END)
    return g.compile()
```

`fact_check` and `rules_check` each append to `violations`; the node after them increments `attempt` when anything failed. On a retry, `write` gets the exact violation strings as feedback ("remove 14 Nov, it is not in the source"). The journal graph is wired the same way with `verify` as its critic.

### Key prompts (in `prompts/`, never inline)

**journal.txt**

```
You are summarizing a person's captured work notes into a journal.
Return JSON: {"lines": [{"text": "...", "cites": [capture ids]}]}.
Each line is one concrete thing done, decided, or learned. Use only what is in the captures.
Every line must cite the capture ids it came from. Do not add numbers, dates or links that
are not in the cited captures. No filler, no praise.

CAPTURES:
{captures}
```

**draft.txt**

```
Write a {platform} post in the same voice as the EXAMPLES.
Use ONLY the facts in SOURCE. Do not add dates, times, numbers, links, names or @handles
that are not in SOURCE. Obey the rules: {rules}.
{feedback}

EXAMPLES (past posts by the same author):
{voice_examples}

SOURCE:
{source_text}

BRIEF: {brief}
```

Where `feedback` is empty on the first attempt and lists the exact violations on retries.

### UI notes (Streamlit)

- **Home**: weekly review plus nudges.
- **Inbox**: paste box, file drop, "scan repo" button, list of recent captures with origin tags.
- **Journal**: day view with each line expandable to its source captures, plus approve and edit.
- **Workspaces**: pick a workspace, see its voice examples, draft from journal lines or a brief, view fact and rules warnings in red beside the draft, one-click "repurpose to...".
- **Planner**: week table with posting slots and deadlines, "download .ics".
- **Ideas**: cards by status with effort and impact, duplicate warnings.
- **Jobs**: columns by status, deadline sort, "tailor to my work" button.

---

## 9. Local model setup

| Laptop RAM | Suggested text model (4-bit) | Approx. memory | Notes |
|---|---|---|---|
| 4 GB | Llama 3.2 1B or Gemma 3 1B | ~1 GB | Fine for journal digests; drafts will be weaker, so lean on the template fallback |
| 8 GB | Qwen2.5 3B, Llama 3.2 3B or Gemma 3 4B | ~2-3.5 GB | Best default |
| 16 GB | A 7B/8B model | ~5 GB | For the comparison section, and likely the best voice match |

The embedding model (`nomic-embed-text`) is small enough to run alongside any of these. Newer small models may beat these picks; the size tiers still apply.

```bash
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

Rules of thumb: modest `num_ctx` (journal prompts trim captures to fit), temperature near 0 for journal lines and around 0.4 for drafts, structured output for every model call that feeds code, and the model unloads when a batch finishes. Everything runs offline after the one-time model download.

---

## 10. Evaluation plan (the technical half of the post)

Use your own real data from two weeks of use, plus planted-error fixtures.

| Metric | How |
|---|---|
| Unsupported-line rate | Journal lines that fail the citation check on first attempt, per model, and how many the retry fixes |
| Fact-check catch rate | Take 30 drafts, plant one wrong date, link or number in each, and count how many `check_facts` catches. Also record false alarms |
| Voice match | Blind test: mix 10 of your real posts with 10 generated ones and ask 5 people to pick the generated ones. Report the guess rate |
| Platform-rule pass rate | Drafts passing length, hashtag and banned-phrase checks on the first attempt vs after retries |
| Edit distance | How much you change each draft before publishing (characters changed over characters). Falling over time means the voice is improving |
| Time to post | Minutes from "I should post" to published, with the tool vs your usual way |
| Posting consistency | Posts per week per workspace in the 2 weeks before vs the 2 weeks after you start using it. This is your headline result |
| Capture coverage | Share of your week's real work that ended up in the desk (self-estimate) |
| Job-tailoring grounding | Share of resume bullets whose citations survive verification |
| Speed and RAM | Seconds per journal entry and per draft, peak RAM via `psutil` |

Compare the same fixtures across a 1B, 3B and (if your RAM allows) 7B model, plus the template fallback as baseline. Save to `eval/results.csv` and put one table in the post. Keep a list of every invented fact the checkers caught; it makes a good "what went wrong" section.

---

## 11. Building with opencode

Put this plan at `docs/PLAN.md` and add an `AGENTS.md` at the repo root. opencode reads project rules from `AGENTS.md` (check your version's docs for the exact behavior). A starting point:

```markdown
# AGENTS.md

Source of truth: docs/PLAN.md. Build one milestone per session, on its own branch.

## Rules
- All verifiers (src/cdesk/verify.py, planner.py) are deterministic and need unit tests first,
  including planted-error cases. Do not change a threshold or regex without updating its tests.
- No network calls except to local Ollama. No telemetry. No cloud SDKs.
- Every LLM call uses structured output (pydantic schema) and has a template fallback.
- Prompts live in src/cdesk/prompts/*.txt, never inline.
- Never commit anything under data/. Never print capture bodies in logs.
- Schema changes go through db.py migrations; ask before changing a table.
- Run pytest before every commit. Small commits. Close issues with "Closes #n".
```

Workflow tips:
- Start each session with: "Implement milestone M2 from docs/PLAN.md. Acceptance criteria are in the table. Write tests first for verify.py."
- Review every diff that touches `verify.py`. The checkers are the product's credibility, and a coding agent can quietly loosen them to make a test pass.
- After each milestone, run the app on your real captures before moving on.

---

## 12. Business angle and first users

You are user #1, and the quickest honest result is your own posting consistency before and after.

**Who else would use it.** Other society officers who run several channels, students building in public for internships, and bootcamp or fellowship cohorts who need to post and track applications. Start with one: give a workspace to an officer of another society and watch what they ask for first.

**What would make someone pay.** Students rarely pay for tools, so test this before assuming. Hypotheses to try: a free local tool plus a paid setup-and-voice-tuning service for societies; a paid hosted sync for people who want it on their phone; or a cohort licence for programs. Ask each user what they would choose and report the answers, even if the answer is "I would use it but not pay."

**Open-source story.** Your private journal and job applications stay on your machine. You can swap models, tune the voice on your own posts at no per-token cost, and sit above four different AI accounts without depending on any of them.

---

## 13. GitHub project plan

Time estimates assume opencode writes most of the code, and include your review, testing and fixes (~26 hours). Add your own due dates to each milestone.

| Milestone | Goal | Est. | Done when |
|---|---|---|---|
| M0 Setup and data model | Repo, env, schema, config, stubbed graphs, CLI skeleton | 2 h | `desk --help` works; schema creates; graphs run end to end with stubs |
| M1 Capture | Paste, files, git, chat-export parser, dedupe, search | 3 h | A week of your real work is in the inbox, tagged by origin, and searchable |
| M2 Journal graph | Summarize, verify, retry, store, fallback | 3 h | A day's captures become a cited journal; an invented number is caught in a planted test |
| M3 Workspaces and voice | Workspaces, voice corpus, embeddings, rules config | 3 h | Past posts imported per workspace; top-3 voice examples retrieved |
| M4 Draft graph | Gather, write, fact check, rules check, retry, repurpose | 4 h | A journal entry becomes drafts for LinkedIn and your society; a planted wrong date is caught and retried |
| M5 Planner and nudges | Calendar view, reminders, nudges, `.ics` export, weekly review | 3 h | Overdue-workspace nudge appears; `.ics` opens in Google Calendar |
| M6 Organizers | Ideas (status, scores, duplicates), job tracker, tailoring graph, context packs | 4 h | Duplicate ideas flagged; a job description produces cited resume bullets; a context pack pastes cleanly into a chat |
| M7 Eval, dogfood, write-up | Comparison table, two weeks of real use, post | 4 h | `eval/results.csv` filled; before/after posting numbers captured; post drafted and submitted |

**Dogfood early.** Start using it for real after M2 and keep a log. Start the 2-week consistency measurement as soon as M4 works, not at the end.

**If you fall behind:** M6's job tailoring and duplicate detection are the first things to defer. The core (M1-M5 plus the eval) is the story.

### Issues by milestone

**M0 Setup and data model**
- [ ] Create repo, `pyproject.toml`, `.gitignore` (ignore `data/`), MIT license, `AGENTS.md`, `docs/PLAN.md`
- [ ] Schema and migrations in `db.py`
- [ ] `config.py` with models and platform rules
- [ ] Stub all graphs and wire them; add a typer CLI skeleton
- [ ] Install Ollama, pull a text model and the embedding model, confirm structured output and `embed` work

**M1 Capture**
- [ ] Paste and quick-add capture with content-hash dedupe
- [ ] File drop (markdown, text) and optional drop-folder watcher
- [ ] Chat-export parser: check each tool's export format; paste fallback
- [ ] Git capture, one note per repo per day
- [ ] FTS search over captures
- [ ] Origin tagging (which AI account or tool)

**M2 Journal graph**
- [ ] `select` and `summarize` with structured output
- [ ] `unsupported_reasons` with unit tests (missing cite, unknown id, invented number, invented URL)
- [ ] Verify node and retry with feedback; drop and warn on lines that stay unsupported
- [ ] Deterministic fallback digest
- [ ] Journal page with lines expandable to sources
- [ ] Weekly entry generation

**M3 Workspaces and voice**
- [ ] Workspace CRUD with rules, cadence and audience
- [ ] Import past posts per workspace (paste or file)
- [ ] Embeddings stored as BLOB; `top_k` tested
- [ ] Voice examples shown on the workspace page
- [ ] Banned-phrase list editor

**M4 Draft graph**
- [ ] `gather` from journal lines, a post, an idea, or a brief
- [ ] `write` with the draft prompt and structured retry feedback
- [ ] `extract_facts` and `check_facts` with unit tests (dates, times, URLs, handles, numbers)
- [ ] `check_rules` with unit tests
- [ ] Router with `MAX_ATTEMPTS = 2`; save with warnings
- [ ] Template fallback
- [ ] Repurpose action across workspaces
- [ ] Drafts page with warnings in red

**M5 Planner and nudges**
- [ ] Post scheduling and status changes
- [ ] `due_nudges` with tests (never posted, on time, overdue)
- [ ] Reminders table and weekly review page
- [ ] Week and month planner view
- [ ] `to_ics` export; verify it imports into Google Calendar
- [ ] Nudge text template and optional "drafts ready" suggestion

**M6 Organizers**
- [ ] Idea cards with status, effort, impact, next step, links to captures
- [ ] Duplicate-idea detection with a tunable threshold
- [ ] Job kanban with deadlines and follow-up reminders
- [ ] Job tailor graph: `parse_jd`, `match_evidence`, `write_bullets`, citation verify
- [ ] Cover letter draft grounded in cited lines
- [ ] Context pack generator and a CLI command

**M7 Eval, dogfood, write-up**
- [ ] `eval/run_eval.py`, fixtures with planted errors, `models.yaml`
- [ ] Run 1B, 3B and 7B (if RAM) plus template baseline
- [ ] Blind voice test with 5 people
- [ ] Two weeks of posting data, before vs after
- [ ] Give a workspace to a second user; record what they ask for
- [ ] Draft the post (outline below)
- [ ] README: install, run, model table, offline and privacy notes
- [ ] Submit

### Create it all with the GitHub CLI

Run from inside the cloned repo (needs `gh auth login` first), in Git Bash on Windows.

```bash
#!/usr/bin/env bash
set -e

# Labels
gh label create setup      --color C5DEF5 --force
gh label create capture    --color 0E8A16 --force
gh label create journal    --color 5319E7 --force
gh label create drafting   --color FBCA04 --force
gh label create planner    --color 1D76DB --force
gh label create organizers --color BFD4F2 --force
gh label create eval       --color D93F0B --force
gh label create writing    --color 0052CC --force

# Milestones (add due_on in ISO 8601 if you want deadlines: -f due_on="2026-10-25T23:59:00Z")
for m in "M0 Setup and data model" "M1 Capture" "M2 Journal graph" "M3 Workspaces and voice" \
         "M4 Draft graph" "M5 Planner and nudges" "M6 Organizers" "M7 Eval, dogfood, write-up"; do
  gh api "repos/{owner}/{repo}/milestones" -f title="$m" >/dev/null
done

mk() { gh issue create --title "$1" --milestone "$2" --label "$3" --body "$4"; }

# M0
mk "Repo skeleton, AGENTS.md, docs/PLAN.md"      "M0 Setup and data model" setup "pyproject, .gitignore (data/), MIT license."
mk "Schema and migrations"                        "M0 Setup and data model" setup "db.py as in the plan."
mk "config.py: models and platform rules"         "M0 Setup and data model" setup "Verify platform limits."
mk "Stub graphs and CLI skeleton"                 "M0 Setup and data model" setup "Graphs run end to end with stubs."
mk "Ollama: text model, embeddings, structured output" "M0 Setup and data model" setup "Confirm chat with format=schema and embed work."

# M1
mk "Paste and quick-add capture with dedupe"      "M1 Capture" capture "Content-hash dedupe."
mk "File drop and drop-folder watcher"            "M1 Capture" capture "Markdown and text."
mk "Chat-export parser"                           "M1 Capture" capture "Check each tool's export format; paste fallback."
mk "Git capture per repo per day"                 "M1 Capture" capture "One note per day, not per commit."
mk "FTS search over captures"                     "M1 Capture" capture "SQLite FTS5."
mk "Origin tagging"                               "M1 Capture" capture "Which AI account or tool."

# M2
mk "select and summarize nodes"                   "M2 Journal graph" journal "Structured output: lines with cites."
mk "unsupported_reasons with unit tests"          "M2 Journal graph" journal "Missing cite, unknown id, invented number, invented URL."
mk "Verify node and retry with feedback"          "M2 Journal graph" journal "Max 2; drop and warn on persistent failures."
mk "Deterministic fallback digest"                "M2 Journal graph" journal "Works with Ollama off."
mk "Journal page with source expansion"           "M2 Journal graph" journal "Each line expands to its captures."
mk "Weekly entry generation"                      "M2 Journal graph" journal "Weekly summary from daily lines."

# M3
mk "Workspace CRUD with rules and cadence"        "M3 Workspaces and voice" drafting "Substack, LinkedIn, society, personal."
mk "Import past posts per workspace"              "M3 Workspaces and voice" drafting "Voice corpus."
mk "Embeddings as BLOB and top_k tests"           "M3 Workspaces and voice" drafting "Shared helpers."
mk "Show voice examples on workspace page"        "M3 Workspaces and voice" drafting "Top 3 similar past posts."
mk "Banned-phrase list editor"                    "M3 Workspaces and voice" drafting "Grow from your own edits."

# M4
mk "gather node"                                  "M4 Draft graph" drafting "Journal lines, post, idea or brief."
mk "write node with retry feedback"               "M4 Draft graph" drafting "Prompt from prompts/draft.txt."
mk "extract_facts and check_facts with tests"     "M4 Draft graph" drafting "Dates, times, URLs, handles, numbers."
mk "check_rules with tests"                       "M4 Draft graph" drafting "Length, hashtags, banned phrases."
mk "Router, MAX_ATTEMPTS and save with warnings"  "M4 Draft graph" drafting "Human sees leftover warnings."
mk "Template fallback for drafts"                 "M4 Draft graph" drafting "Works with Ollama off."
mk "Repurpose across workspaces"                  "M4 Draft graph" drafting "One post, several channels."
mk "Drafts page with red warnings"                "M4 Draft graph" drafting "Show violations beside the text."

# M5
mk "Scheduling and post status flow"              "M5 Planner and nudges" planner "idea to published."
mk "due_nudges with tests"                        "M5 Planner and nudges" planner "Never posted, on time, overdue."
mk "Reminders and weekly review page"             "M5 Planner and nudges" planner "One-page review."
mk "Week and month planner view"                  "M5 Planner and nudges" planner "Posting slots and deadlines."
mk "to_ics export"                                "M5 Planner and nudges" planner "Verify import into Google Calendar."
mk "Nudge text and drafts-ready suggestion"       "M5 Planner and nudges" planner "Template first, optional draft run."

# M6
mk "Idea cards and statuses"                      "M6 Organizers" organizers "Effort, impact, next step, source links."
mk "Duplicate-idea detection"                     "M6 Organizers" organizers "Tunable cosine threshold."
mk "Job kanban with deadlines and reminders"      "M6 Organizers" organizers "Follow-up reminders."
mk "Job tailor graph"                             "M6 Organizers" organizers "parse_jd, match_evidence, write_bullets, verify."
mk "Cover letter draft grounded in cited lines"   "M6 Organizers" organizers "Reuse the citation verifier."
mk "Context pack generator and CLI command"       "M6 Organizers" organizers "Paste-ready project brief."

# M7
mk "Eval script, fixtures, models.yaml"           "M7 Eval, dogfood, write-up" eval "eval/run_eval.py with planted errors."
mk "Run model comparison and template baseline"   "M7 Eval, dogfood, write-up" eval "1B, 3B, 7B if RAM."
mk "Blind voice test"                             "M7 Eval, dogfood, write-up" eval "10 real vs 10 generated, 5 people."
mk "Two weeks of posting data"                    "M7 Eval, dogfood, write-up" eval "Before vs after."
mk "Second user trial"                            "M7 Eval, dogfood, write-up" writing "Record what they ask for and whether they would pay."
mk "Draft the post"                               "M7 Eval, dogfood, write-up" writing "Use the outline in the plan."
mk "Final README"                                 "M7 Eval, dogfood, write-up" writing "Install, run, models, offline and privacy notes."
mk "Submit"                                       "M7 Eval, dogfood, write-up" writing "Check the judging criteria one last time."
```

Suggested branch and commit style: one branch per milestone (`m4-draft-graph`), small commits, close issues with `Closes #n` in the PR.

---

## 14. Writing the post

**Outline**
1. **Open with the mess.** Four AI accounts, scattered notes, a Substack that has not been updated in weeks. One real example of work that never became a post.
2. **The problem in one paragraph.** Work is scattered across tools, so posting depends on memory and mood. Existing caption tools start from a blank box.
3. **Why open matters here.** The journal and job applications are private. You are not locked into any one AI account. The voice is tuned on your own posts at no per-token cost. Models are swappable, and you show the 1B, 3B and 7B drafts side by side.
4. **How it works, briefly.** One diagram of capture, journal, draft and verify, plus "the model writes, code verifies" and why.
5. **What went wrong.** At least one honest failure: an invented date the fact-check caught (or missed), a journal line that cited the wrong capture, a draft that sounded like a press release until the banned-phrase list fixed it.
6. **The numbers.** Unsupported-line rate, fact-check catch rate, blind voice test, posting consistency before and after, edit distance over time.
7. **Second user.** What they asked for first, and whether they would pay.
8. **Close with the habit.** Posts per week before and after, and what the journal now lets you say that you used to forget.

**Style reminders**
- Concrete over abstract: a real capture, the line the model wrote, the check that caught it.
- Show one real nudge, one draft with its red warnings, and one `.ics` event on the calendar.
- Keep the technical section short; the story is the habit it built.

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Chat-export formats differ or change | Paste and file drop always work; write one parser at a time and test with real exports |
| Small model invents facts | Citations on every journal line, fact-check on every draft, retry with exact feedback, human approval before anything is marked approved |
| Drafts sound generic | Retrieve closest past posts as examples, grow the banned-phrase list from your edits, track edit distance, consider a small fine-tune later |
| Platform limits change | Keep limits in `config.py`, verify before shipping, note the date checked |
| Too many features, thin quality | Build and dogfood in milestone order, and defer job tailoring and duplicate detection first |
| Coding agent loosens the verifiers | Tests first, review every diff touching `verify.py`, rules in `AGENTS.md` |
| Sensitive data (journal, job applications) | Local SQLite only, `data/` gitignored, no telemetry, back up by copying one file |
| Students will not pay | Measure it honestly; report usage and willingness, and note the paid angles you would try next |
| Embedding-based matches are noisy | Tune thresholds on your own data, show matches for confirmation instead of acting on them automatically |
| Run out of time | Use the cut line in section 13 |
