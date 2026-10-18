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

## Current milestone: M1 Capture
- [x] Paste and quick-add capture with content-hash dedupe
- [x] File drop and drop-folder watcher
- [x] Chat-export parser (ChatGPT JSON, generic messages, markdown transcripts; paste fallback)
- [x] Git capture per repo per day
- [x] FTS search over captures (triggers keep the index in sync)
- [x] Origin tagging (--origin flag, CDESK_ORIGIN env, default "unknown")

## Notes for later milestones
- Schema is at v2 (FTS sync triggers). Bump MIGRATIONS in db.py for any table change;
  never edit a released migration.
- Git `--since` bare dates are end-of-day approxidate in git >= 2.5x; pass full timestamps.
- The CLI is `cdesk`, not `desk` (Windows desk.cpl collision).
- CLI never prints capture bodies (AGENTS.md rule); listings are id/date/origin/title only.
