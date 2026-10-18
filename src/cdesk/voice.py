"""Embeddings and nearest past posts (voice retrieval). See docs/PLAN.md section 7.

Embeddings are stored as little-endian float32 bytes in SQLite BLOB columns
(arr.tobytes() / np.frombuffer). top_k is pure numpy and unit-tested without
a model; only embed_texts needs Ollama.
"""

import numpy as np

from .config import EMBED_MODEL


def vec_to_blob(arr: np.ndarray) -> bytes:
    return np.asarray(arr, dtype="float32").tobytes()


def blob_to_vec(b: bytes) -> np.ndarray:
    if not b:
        raise ValueError("empty embedding blob")
    return np.frombuffer(b, dtype="float32")


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts via local Ollama (nomic-embed-text by default)."""
    from .llm import embed
    return np.array(embed(texts, model=EMBED_MODEL), dtype="float32")


def top_k(query_vec: np.ndarray, mat: np.ndarray, k: int = 3) -> list[int]:
    """Indices of the k most cosine-similar rows, best first."""
    if mat.ndim != 2 or mat.shape[0] == 0:
        return []
    k = min(k, mat.shape[0])
    denom = (np.linalg.norm(mat, axis=1) * np.linalg.norm(query_vec) + 1e-9)
    sims = (mat @ query_vec) / denom
    return list(np.argsort(-sims)[:k])


def voice_examples(
    conn,
    workspace_id: int,
    query: str,
    k: int = 3,
    embedder=None,
) -> list[dict]:
    """The k most similar indexed past posts for a query, as style examples."""
    embedder = embedder or embed_texts
    rows = conn.execute(
        "SELECT id, body, url, embedding FROM past_post "
        "WHERE workspace_id = ? AND embedding IS NOT NULL",
        (workspace_id,),
    ).fetchall()
    if not rows:
        return []
    mat = np.stack([blob_to_vec(r["embedding"]) for r in rows])
    q = embedder([query])[0]
    idx = top_k(np.asarray(q, dtype="float32"), mat, k=k)
    return [
        {"id": rows[i]["id"], "body": rows[i]["body"], "url": rows[i]["url"]}
        for i in idx
    ]
