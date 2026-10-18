"""Voice and embedding tests (M3 #20). top_k is pure numpy — no model needed."""

import numpy as np
import pytest

from cdesk.voice import blob_to_vec, top_k, vec_to_blob


# --- BLOB storage -----------------------------------------------------------

def test_blob_roundtrip():
    arr = np.array([0.1, -0.2, 0.3], dtype="float32")
    b = vec_to_blob(arr)
    back = blob_to_vec(b)
    assert back.dtype == np.float32
    np.testing.assert_array_equal(arr, back)


def test_blob_empty():
    with pytest.raises(ValueError):
        blob_to_vec(b"")


# --- top_k ------------------------------------------------------------------

def test_top_k_ordering():
    mat = np.array([
        [1.0, 0.0, 0.0],   # matches x-axis
        [0.0, 1.0, 0.0],   # matches y-axis
        [0.7, 0.7, 0.0],   # in between
    ], dtype="float32")
    q = np.array([1.0, 0.0, 0.0], dtype="float32")
    assert top_k(q, mat, k=3) == [0, 2, 1]


def test_top_k_k_clamped_to_matrix_size():
    mat = np.array([[1.0], [0.5]], dtype="float32")
    q = np.array([1.0], dtype="float32")
    assert len(top_k(q, mat, k=10)) == 2


def test_top_k_k_one_returns_best():
    mat = np.array([[-1.0, 0.0], [0.9, 0.1], [1.0, 0.0]], dtype="float32")
    q = np.array([1.0, 0.0], dtype="float32")
    assert top_k(q, mat, k=1) == [2]


def test_top_k_zero_query_is_safe():
    mat = np.array([[1.0, 2.0]], dtype="float32")
    q = np.zeros(2, dtype="float32")
    result = top_k(q, mat, k=1)
    assert result == [0]  # no NaN crash; epsilon guards the norm


def test_top_k_identical_vectors_tie_by_index_order():
    mat = np.array([[1.0, 0.0], [1.0, 0.0]], dtype="float32")
    q = np.array([1.0, 0.0], dtype="float32")
    assert top_k(q, mat, k=2) == [0, 1]


# --- voice examples with a fake embedder ------------------------------------

@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def workspace(conn):
    from cdesk.workspaces import create_workspace
    return create_workspace(conn, "LinkedIn", kind="linkedin")


FAKE_VECS = {
    "short technical post about databases": [1.0, 0.0],
    "long story about my cat": [0.0, 1.0],
    "shipping a compiler in a weekend": [0.9, 0.1],
}


def _fake_embed(texts, model=None):
    return [FAKE_VECS.get(t, [0.5, 0.5]) for t in texts]


def test_voice_examples_retrieves_top3(conn, workspace, monkeypatch):
    from cdesk import voice
    from cdesk.workspaces import add_past_post, index_workspace_embeddings

    for body in FAKE_VECS:
        add_past_post(conn, workspace["id"], body)
    monkeypatch.setattr(voice, "embed_texts", lambda texts: np.array(_fake_embed(texts), dtype="float32"))
    index_workspace_embeddings(conn, workspace["id"], embedder=voice.embed_texts)

    examples = voice.voice_examples(
        conn, workspace["id"], "short technical post about databases", k=2,
        embedder=voice.embed_texts,
    )
    assert len(examples) == 2
    assert examples[0]["body"] == "short technical post about databases"
    assert examples[1]["body"] == "shipping a compiler in a weekend"


def test_voice_examples_empty_workspace(conn, workspace):
    from cdesk.voice import voice_examples
    assert voice_examples(conn, workspace["id"], "anything") == []


def test_index_skips_posts_with_embeddings(conn, workspace, monkeypatch):
    from cdesk import voice
    from cdesk.workspaces import add_past_post, index_workspace_embeddings

    ids = [add_past_post(conn, workspace["id"], body) for body in list(FAKE_VECS)[:2]]
    calls = []

    def counting_embed(texts, model=None):
        calls.append(list(texts))
        return _fake_embed(texts)

    monkeypatch.setattr(voice, "embed_texts", counting_embed)
    index_workspace_embeddings(conn, workspace["id"], embedder=voice.embed_texts)
    index_workspace_embeddings(conn, workspace["id"], embedder=voice.embed_texts)
    assert len(calls) == 1  # second run had nothing to embed
    rows = conn.execute("SELECT embedding FROM past_post").fetchall()
    assert all(r["embedding"] is not None for r in rows)
