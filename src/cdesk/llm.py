"""Ollama chat and embed wrappers with graceful degradation.

Every model call that feeds code uses structured output (a pydantic schema).
When Ollama is unreachable or a call fails, callers fall back to deterministic
templates — see graphs/* fallbacks and docs/PLAN.md section 3.
"""

from typing import TypeVar

import ollama
from pydantic import BaseModel

from .config import EMBED_MODEL

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Ollama is not running or the requested model is missing."""


def ollama_available() -> bool:
    try:
        ollama.list()
        return True
    except Exception:
        return False


def models_present(*names: str) -> dict[str, bool]:
    """Check which of the given models are pulled locally."""
    if not ollama_available():
        return {n: False for n in names}
    try:
        have = {m["model"] for m in ollama.list().get("models", [])}
    except Exception:
        return {n: False for n in names}
    return {n: any(n in h for h in have) for n in names}


def chat(
    messages: list[dict],
    model: str,
    schema: type[T] | None = None,
    temperature: float = 0.0,
) -> str | T:
    """Chat completion. With schema, parse structured output into the model.

    Raises LLMUnavailable when Ollama cannot serve the call, so callers can
    run their template fallback instead of swallowing real errors.
    """
    kwargs: dict = {"model": model, "messages": messages, "options": {"temperature": temperature}}
    if schema is not None:
        kwargs["format"] = schema.model_json_schema()
    try:
        r = ollama.chat(**kwargs)
    except Exception as e:
        raise LLMUnavailable(str(e)) from e
    content = r["message"]["content"]
    if schema is None:
        return content
    return schema.model_validate_json(content)


def embed(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """Embed a batch of texts. Raises LLMUnavailable when Ollama is down."""
    try:
        r = ollama.embed(model=model, input=texts)
    except Exception as e:
        raise LLMUnavailable(str(e)) from e
    return r["embeddings"]
