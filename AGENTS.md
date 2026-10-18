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

## Workflow
- Start each session with: "Implement milestone Mn from docs/PLAN.md. Acceptance criteria are
  in the milestone table. Write tests first for verify.py."
- Review every diff that touches verify.py. The checkers are the project's credibility, and a
  coding agent can quietly loosen them to make a test pass.
- After each milestone, run the app on real captures before moving on.

## Completed milestones
### M1 Capture
- Paste/quick-add with content-hash dedupe; file drop + drop-folder watcher
- Chat-export parser (ChatGPT JSON, generic messages, markdown; paste fallback)
- Git capture per repo per day; FTS search (trigger-synced); origin tagging

### M2 Journal graph
- unsupported_reasons with planted-error unit tests (verify.py)
- select and summarize nodes with structured output; verify, retry with exact feedback
- Deterministic fallback digest (daily per-capture, weekly per-day)
- CLI `cdesk journal --day/--weekly` wired to the DB; Journal Streamlit page

## Current milestone: M3 Workspaces and voice
- [x] Workspace CRUD with rules and cadence (cdesk.workspaces, #18)
- [x] Import past posts per workspace; text/JSON parsers, BOM tolerated (#19)
- [x] Embeddings as BLOB + top_k tests (cdesk.voice, injectable embedder, #20)
- [x] Voice examples on Workspaces Streamlit page + `cdesk workspace voice` (#21)
- [x] Banned-phrase editor (page + `cdesk workspace ban/unban`, #22)

## Notes for later milestones
- Schema is at v2 (FTS sync triggers). Bump MIGRATIONS in db.py for any table change;
  never edit a released migration.
- Git `--since` bare dates are end-of-day approxidate in git >= 2.5x; pass full timestamps.
- The CLI is `cdesk`, not `desk` (Windows desk.cpl collision).
- CLI never prints capture bodies (AGENTS.md rule); listings are id/date/origin/title only.
- Prompt files contain JSON braces: use str.replace("{captures}", ...), not str.format().
- The weekly prompt must list allowed capture ids explicitly, or small models invent ids
  (the verifier drops them all — do not loosen the check to compensate).
- Fallback digest line text must never add ids/dates the source lacks; the verifier
  will (rightly) drop them.
- Windows: imported files often carry a UTF-8 BOM (parsers strip it) and consoles
  default to cp1252 (cli.py reconfigures stdout to utf-8/replace — keep that).
