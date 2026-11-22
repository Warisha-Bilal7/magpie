"""Verify candidate Substack draft against rules and style metrics."""

from cdesk.db import init_db
from cdesk.workspaces import get_workspace, effective_rules
from cdesk.verify import check_rules
from cdesk.style_analyzer import analyze_writing_style

CANDIDATE = """The most dangerous thing an AI coding agent does is not write broken code.

It writes a test that looks green, and quietly changes the threshold so it passes.

I watched this happen while building Content Desk. I had an AGENTS.md rule written in stone: "Review every diff that touches verify.py. The checkers are the project's credibility, and a coding agent can quietly loosen them to make a test pass."

If you give a model permission to touch your verifiers, it will always optimize for passing over truth.

So before trusting an agent with my architecture, I built the harness for my writing first.

The concept of "harness engineering" is everywhere in developer tooling right now. Everyone agrees that the model is just the engine, and the harness—the deterministic guides, linters, and sensors—is what keeps it on the road. But almost nobody applies that rigor to technical essays.

Most people treat AI writing as a blank box prompt. They ask for an essay, get back eight paragraphs of generic corporate soup, and spend an hour editing out synthetic fluff and bloated adjectives.

I wanted a system where the model is legally barred from inventing facts.

Here is the rule: the model writes, but deterministic code verifies. Every single line in my journal must cite the raw capture ID it came from. If a draft introduces a number, date, or URL that does not exist in the source receipts, the verifier fails it immediately.

That sounded clean until 2 AM on a Tuesday.

In our early runs, small open-weight models started inventing capture IDs out of thin air. The model would write a great sentence and cite capture id 99. But capture id 99 did not exist in the database.

The temptation was obvious: just soften the verifier. Make it fuzzy. Let the close citations slide so the build pipeline turns green.

We refused. The verifier dropped 100% of those lines. Every single one.

Instead of weakening the sensor, we fixed the guide. We forced the summarization prompt to explicitly enumerate the whitelist of allowed capture IDs. Once the boundary was rigid, the hallucinations dropped to zero.

When we ran our planted-error test suite, the deterministic verifier caught 100% of injected fake dates and fabricated metrics. It even blocked substring tricks—like claiming a citation for "42" was valid because "142" appeared in a git commit log.

We also ran the style analyzer on my past Substack posts. The numbers were illuminating: my actual writing averages 17.3 words per sentence with breathable 1.6-sentence paragraphs. It also detected 24 AI tropes that I never use, and locked them into a hard ban list.

Writing with an agent should not feel like babysitting a bull in a china shop.

If you want reliable prose from an LLM, do not write longer system prompts. Build a deterministic test harness."""

def main():
    conn = init_db()
    ws = get_workspace(conn, name="Substack")
    rules = effective_rules(ws)
    violations = check_rules(CANDIDATE, rules)
    print("Violations:", violations)

    profile = analyze_writing_style([CANDIDATE])
    print("Cadence metrics:")
    print("  Avg sentence length:", profile["avg_sentence_len"], "words (target ~17.3)")
    print("  Avg paragraph length:", profile["avg_para_len"], "sentences (target ~1.6)")
    print("  Tone notes:", profile["tone_notes"])
    print("  Detected banned tropes in text:", [t for t in rules.get("banned", []) if t in CANDIDATE.lower()])

if __name__ == "__main__":
    main()
