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

## Current milestone: M0 Setup and data model
- [x] Repo skeleton, AGENTS.md, docs/PLAN.md
- [x] Schema and migrations in db.py
- [x] config.py with models and platform rules
- [x] Stub graphs and CLI skeleton
- [ ] Ollama: confirm structured output and embeddings work (run `desk doctor`)
