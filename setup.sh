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

# Get current repository owner and name automatically
REPO=$(gh repo view --json owner,name --jq '.owner.login + "/" + .name')

# Milestones
for m in "M0 Setup and data model" "M1 Capture" "M2 Journal graph" "M3 Workspaces and voice" \
         "M4 Draft graph" "M5 Planner and nudges" "M6 Organizers" "M7 Eval, dogfood, write-up"; do
  gh api "repos/$REPO/milestones" -f title="$m" >/dev/null
done

mk() { gh issue create --title "$1" --milestone "$2" --label "$3" --body "$4"; }

# M0
mk "Repo skeleton, AGENTS.md, docs/PLAN.md"      "M0 Setup and data model" setup "pyproject, .gitignore (data/), MIT license."[cite: 3]
mk "Schema and migrations"                        "M0 Setup and data model" setup "db.py as in the plan."[cite: 3]
mk "config.py: models and platform rules"         "M0 Setup and data model" setup "Verify platform limits."[cite: 3]
mk "Stub graphs and CLI skeleton"                 "M0 Setup and data model" setup "Graphs run end to end with stubs."[cite: 3]
mk "Ollama: text model, embeddings, structured output" "M0 Setup and data model" setup "Confirm chat with format=schema and embed work."[cite: 3]

# M1
mk "Paste and quick-add capture with dedupe"      "M1 Capture" capture "Content-hash dedupe."[cite: 3]
mk "File drop and drop-folder watcher"            "M1 Capture" capture "Markdown and text."[cite: 3]
mk "Chat-export parser"                           "M1 Capture" capture "Check each tool's export format; paste fallback."[cite: 3]
mk "Git capture per repo per day"                 "M1 Capture" capture "One note per day, not per commit."[cite: 3]
mk "FTS search over captures"                     "M1 Capture" capture "SQLite FTS5."[cite: 3]
mk "Origin tagging"                               "M1 Capture" capture "Which AI account or tool."[cite: 3]

# M2
mk "select and summarize nodes"                   "M2 Journal graph" journal "Structured output: lines with cites."[cite: 3]
mk "unsupported_reasons with unit tests"          "M2 Journal graph" journal "Missing cite, unknown id, invented number, invented URL."[cite: 3]
mk "Verify node and retry with feedback"          "M2 Journal graph" journal "Max 2; drop and warn on persistent failures."[cite: 3]
mk "Deterministic fallback digest"                "M2 Journal graph" journal "Works with Ollama off."[cite: 3]
mk "Journal page with source expansion"           "M2 Journal graph" journal "Each line expands to its captures."[cite: 3]
mk "Weekly entry generation"                      "M2 Journal graph" journal "Weekly summary from daily lines."[cite: 3]

# M3
mk "Workspace CRUD with rules and cadence"        "M3 Workspaces and voice" drafting "Substack, LinkedIn, society, personal."[cite: 3]
mk "Import past posts per workspace"              "M3 Workspaces and voice" drafting "Voice corpus."[cite: 3]
mk "Embeddings as BLOB and top_k tests"           "M3 Workspaces and voice" drafting "Shared helpers."[cite: 3]
mk "Show voice examples on workspace page"        "M3 Workspaces and voice" drafting "Top 3 similar past posts."[cite: 3]
mk "Banned-phrase list editor"                    "M3 Workspaces and voice" drafting "Grow from your own edits."[cite: 3]

# M4
mk "gather node"                                  "M4 Draft graph" drafting "Journal lines, post, idea or brief."[cite: 3]
mk "write node with retry feedback"               "M4 Draft graph" drafting "Prompt from prompts/draft.txt."[cite: 3]
mk "extract_facts and check_facts with tests"     "M4 Draft graph" drafting "Dates, times, URLs, handles, numbers."[cite: 3]
mk "check_rules with tests"                       "M4 Draft graph" drafting "Length, hashtags, banned phrases."[cite: 3]
mk "Router, MAX_ATTEMPTS and save with warnings"  "M4 Draft graph" drafting "Human sees leftover warnings."[cite: 3]
mk "Template fallback for drafts"                 "M4 Draft graph" drafting "Works with Ollama off."[cite: 3]
mk "Repurpose across workspaces"                  "M4 Draft graph" drafting "One post, several channels."[cite: 3]
mk "Drafts page with red warnings"                "M4 Draft graph" drafting "Show violations beside the text."[cite: 3]

# M5
mk "Scheduling and post status flow"              "M5 Planner and nudges" planner "idea to published."[cite: 3]
mk "due_nudges with tests"                        "M5 Planner and nudges" planner "Never posted, on time, overdue."[cite: 3]
mk "Reminders and weekly review page"             "M5 Planner and nudges" planner "One-page review."[cite: 3]
mk "Week and month planner view"                  "M5 Planner and nudges" planner "Posting slots and deadlines."[cite: 3]
mk "to_ics export"                                "M5 Planner and nudges" planner "Verify import into Google Calendar."[cite: 3]
mk "Nudge text and drafts-ready suggestion"       "M5 Planner and nudges" planner "Template first, optional draft run."[cite: 3]

# M6
mk "Idea cards and statuses"                      "M6 Organizers" organizers "Effort, impact, next step, source links."[cite: 3]
mk "Duplicate-idea detection"                     "M6 Organizers" organizers "Tunable cosine threshold."[cite: 3]
mk "Job kanban with deadlines and reminders"      "M6 Organizers" organizers "Follow-up reminders."[cite: 3]
mk "Job tailor graph"                             "M6 Organizers" organizers "parse_jd, match_evidence, write_bullets, verify."[cite: 3]
mk "Cover letter draft grounded in cited lines"   "M6 Organizers" organizers "Reuse the citation verifier."[cite: 3]
mk "Context pack generator and CLI command"       "M6 Organizers" organizers "Paste-ready project brief."[cite: 3]

# M7
mk "Eval script, fixtures, models.yaml"           "M7 Eval, dogfood, write-up" eval "eval/run_eval.py with planted errors."[cite: 3]
mk "Run model comparison and template baseline"   "M7 Eval, dogfood, write-up" eval "1B, 3B, 7B if RAM."[cite: 3]
mk "Blind voice test"                             "M7 Eval, dogfood, write-up" eval "10 real vs 10 generated, 5 people."[cite: 3]
mk "Two weeks of posting data"                    "M7 Eval, dogfood, write-up" eval "Before vs after."[cite: 3]
mk "Second user trial"                            "M7 Eval, dogfood, write-up" writing "Record what they ask for and whether they would pay."[cite: 3]
mk "Draft the post"                               "M7 Eval, dogfood, write-up" writing "Use the outline in the plan."[cite: 3]
mk "Final README"                                 "M7 Eval, dogfood, write-up" writing "Install, run, models, offline and privacy notes."[cite: 3]
mk "Submit"                                       "M7 Eval, dogfood, write-up" writing "Check the judging criteria one last time."[cite: 3]