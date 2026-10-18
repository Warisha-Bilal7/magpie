"""Paths, model names and platform rules. See docs/PLAN.md section 6."""

from pathlib import Path

# --- paths -----------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "cdesk.db"
DROP_DIR = DATA_DIR / "drop"
EXPORT_DIR = DATA_DIR / "exports"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# --- models ----------------------------------------------------------------
MODEL_NAME = "qwen2.5:3b"  # swap in one line; see docs/PLAN.md section 9
EMBED_MODEL = "nomic-embed-text"

# --- generation ------------------------------------------------------------
MAX_ATTEMPTS = 2
JOURNAL_TEMPERATURE = 0.0
DRAFT_TEMPERATURE = 0.4

# Starting values. VERIFY current platform limits before relying on them.
# (Checked 2026-10; verify again before shipping — see docs/PLAN.md section 15.)
PLATFORM_RULES = {
    "linkedin": {
        "max_chars": 3000,
        "max_hashtags": 5,
        "banned": ["i'm thrilled", "excited to announce", "game-changer"],
    },
    "substack": {"max_chars": 100_000, "max_hashtags": 0, "banned": []},
    # e.g. Instagram caption for a society channel
    "society": {"max_chars": 2200, "max_hashtags": 8, "banned": []},
    "personal": {"max_chars": 100_000, "max_hashtags": 5, "banned": []},
}

DEFAULT_RULES = {"max_chars": 100_000, "max_hashtags": 10, "banned": []}


def ensure_dirs() -> None:
    """Create data directories on first use."""
    for d in (DATA_DIR, DROP_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
