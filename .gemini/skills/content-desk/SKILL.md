---
name: content-desk
description: Local-first work journal, content drafting desk, and multi-model debate engine for technical writing across Substack and LinkedIn. Automates Substack style profiling, captures Antigravity chats, cross-references tech news with personal receipts, and orchestrates dialectical debate between Gemini (synthesis) and Claude (skepticism) perspectives.
---

# Content Desk & Multi-Model Writing Engine

Content Desk turns your scattered daily engineering work—Antigravity sessions, git commits, terminal debugging notes, and architecture decisions—into published Substack articles and LinkedIn posts in your genuine voice, with verifiable receipts and zero AI fluff.

## Core Philosophy

1. **The journal is the center; posts are by-products.** Never write from a blank box. Ground every post in real work you actually executed.
2. **Facts in, prose out, with receipts.** The model only uses verified facts. Every number, date, link, and benchmark must trace back to a capture.
3. **Dialectical Multi-Model Debate:** Instead of single-model sycophancy, simulate or orchestrate a debate between a **Gemini Narrative Synthesizer** (connecting your work to broader tech shifts) and a **Claude Rigorous Skeptic** (poking holes, demanding receipts, cutting fluff).
4. **Automated Style Profiling:** Never waste tokens explaining your tone in prompts. Content Desk reads your published Substack posts, computes sentence/paragraph cadence, detects and bans unused AI tropes, and stores the profile directly in workspace rules.

---

## When to Trigger Content Desk

Activate Content Desk proactively or when the user asks:
- "Let's write a Substack post" or "Draft a LinkedIn update about what we just built".
- "What should I post about this week?" (Trigger tech trends cross-matched with recent receipts).
- "Sync my Substack style" or "Update my voice profile".
- "Debate this idea before writing" (Run the Gemini vs. Claude dialectical loop).

---

## The Dialectical Debate Workflow

When generating a post or exploring an idea, run a structured 3-phase dialectical loop:

### Phase 1: Ingest & Formulate Premise
- Identify the source material (recent Antigravity captures, git commits, or tech news trend).
- Formulate the core thesis (e.g., *"Why synthetic benchmarks fail to capture production hallucination latency"*).

### Phase 2: The Two-Perspective Collision

#### 1. The Synthesizer (Gemini Persona)
- **Role:** Broad narrative vision, ecosystem context, reader stakes.
- **Questions:**
  - Why does this matter right now to builders and engineers?
  - What is the macro industry trend (e.g., trillion-dollar AI tooling shifts, local models, production edge cases)?
  - What is the emotional and intellectual hook that pulls the reader in?

#### 2. The Skeptic (Claude Persona)
- **Role:** Ruthless technical critic, proof-checker, anti-fluff enforcer.
- **Questions:**
  - Where are the exact numbers? Did token bills triple or double?
  - Are we making unsupported generalizations?
  - Does this sound like a marketing pitch or an actual engineer's field report?
  - What failed? (Demands the "2 AM bug" / "witching hour" honesty).

#### 3. The Collision & Consensus
- Synthesizer and Skeptic converge on the sharpest angle: an engineering essay that possesses both narrative resonance AND concrete technical receipts.

---

## Phase 3: Drafting with Auto-Tuned Style Rules

When drafting the post:
1. **Load Workspace Rules:**
   - Adhere strictly to the workspace's `voice_summary` and `tone_notes`.
   - Obey the cadence: e.g., for Substack, aim for average sentence lengths (~17 words) with breathable 1-2 sentence paragraphs.
   - **Enforce Banned Phrases:** Never use words in `banned` (e.g., "delve", "testament", "tapestry", "beacon", "game-changer", "pivotal", "in conclusion").
2. **Receipt Grounding:**
   - Every metric (e.g., "4.2 seconds", "Week 4", "@warishadaninbilal") must exist in the source capture.
   - Run the deterministic fact check (`check_facts` / `unsupported_reasons`).

---

## CLI Integration Reference

Run these commands inside the `magpie` repo (`C:\Users\hp\Downloads\Hackathons\magpie`):

| Action | Command | What it does |
|---|---|---|
| **Sync Substack & Auto-Tune Voice** | `python -m cdesk.cli substack-sync <url_or_handle>` | Pulls articles from Substack, computes sentence/paragraph cadence, bans unused AI clichés, and updates workspace rules. |
| **Ingest Antigravity Chats** | `python -m cdesk.cli antigravity-sync` | Scans session transcripts from `.gemini/antigravity/brain`, extracts decisions, and captures them. |
| **Tech Trends & Post Ideas** | `python -m cdesk.cli tech-trends` | Fetches trending Hacker News stories and cross-matches them with your captures to suggest ideas with receipts. |
| **Search Captures** | `python -m cdesk.cli search "<keyword>"` | FTS5 full-text search over all captures. |
| **Run Daily/Weekly Journal** | `python -m cdesk.cli journal --day <YYYY-MM-DD>` | Generates a cited journal entry from the day's notes. |
| **Draft Post** | `python -m cdesk.cli draft <workspace_id>` | Runs the full draft graph (gather, write, fact-check, rules-check). |
| **Posting Nudge** | `python -m cdesk.cli nudge` | Checks cadence targets and alerts if a channel has gone quiet. |
