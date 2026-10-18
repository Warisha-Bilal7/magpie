"""Idea cards and duplicate detection (M6 #37, #38)."""

import numpy as np
import pytest

from cdesk.ideas import (
    create_idea,
    delete_idea,
    duplicates_for,
    find_duplicates,
    get_idea,
    ideas_by_status,
    index_idea,
    list_ideas,
    update_idea,
)
from cdesk.voice import vec_to_blob


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


class FakeEmbedder:
    """Maps known texts to fixed unit vectors so cosine is predictable."""

    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, texts):
        return [self.mapping[t] for t in texts]


# --- CRUD (#37) -------------------------------------------------------------

def test_create_and_get_idea(conn):
    idea = create_idea(conn, "Local-first posting desk", note="no cloud",
                       effort=3, impact=5, next_step="draft the plan",
                       source_ids=[1, 2])
    assert idea["id"] > 0
    assert idea["status"] == "spark"
    assert idea["effort"] == 3 and idea["impact"] == 5
    fetched = get_idea(conn, idea["id"])
    assert fetched["note"] == "no cloud"
    assert fetched["source_ids"] == [1, 2]


def test_create_rejects_bad_status_and_scores(conn):
    with pytest.raises(ValueError):
        create_idea(conn, "x", status="maybe")
    with pytest.raises(ValueError):
        create_idea(conn, "x", effort=0)
    with pytest.raises(ValueError):
        create_idea(conn, "x", impact=6)
    with pytest.raises(ValueError):
        create_idea(conn, "  ")


def test_update_idea_and_status_flow(conn):
    idea = create_idea(conn, "Ship something")
    update_idea(conn, idea["id"], status="building", next_step="write tests")
    fetched = get_idea(conn, idea["id"])
    assert fetched["status"] == "building"
    assert fetched["next_step"] == "write tests"
    with pytest.raises(ValueError):
        update_idea(conn, idea["id"], status="nope")
    with pytest.raises(ValueError):
        update_idea(conn, idea["id"], oops=1)


def test_list_filter_and_delete(conn):
    a = create_idea(conn, "A", status="spark")
    create_idea(conn, "B", status="parked")
    assert [i["id"] for i in list_ideas(conn)] == [b_id(conn, "B"), a["id"]]
    assert len(list_ideas(conn, status="spark")) == 1
    delete_idea(conn, a["id"])
    assert all(i["title"] != "A" for i in list_ideas(conn))


def b_id(conn, title):
    return next(i["id"] for i in list_ideas(conn) if i["title"] == title)


def test_board_orders_by_impact_then_effort(conn):
    create_idea(conn, "low", status="spark", impact=1, effort=5)
    create_idea(conn, "high", status="spark", impact=5, effort=2)
    create_idea(conn, "mid", status="building", impact=3)
    board = ideas_by_status(conn)
    assert [i["title"] for i in board["spark"]] == ["high", "low"]
    assert [i["title"] for i in board["building"]] == ["mid"]
    assert board["parked"] == []


# --- duplicate detection (#38) ---------------------------------------------

def test_duplicates_for_threshold_boundary():
    a = np.array([1.0, 0.0], dtype="float32")
    same = np.array([1.0, 0.0], dtype="float32")
    near = np.array([0.9, 0.436], dtype="float32")   # cos ~0.9
    far = np.array([0.0, 1.0], dtype="float32")
    rows = [
        {"id": 1, "title": "same", "embedding": vec_to_blob(same)},
        {"id": 2, "title": "near", "embedding": vec_to_blob(near)},
        {"id": 3, "title": "far", "embedding": vec_to_blob(far)},
    ]
    hits = duplicates_for(a, rows, threshold=0.85)
    assert [h["id"] for h in hits] == [1, 2]
    assert hits[0]["score"] > hits[1]["score"] >= 0.85
    assert duplicates_for(a, rows, threshold=0.99) == []


def test_duplicates_for_skips_unembedded_rows():
    a = np.array([1.0, 0.0], dtype="float32")
    rows = [{"id": 1, "title": "no vec", "embedding": None}]
    assert duplicates_for(a, rows) == []


def test_find_duplicates_end_to_end_with_fake_embedder(conn):
    embedder = FakeEmbedder(v)
    a = create_idea(conn, "idea one", note="note one")
    a = create_idea(conn, "idea one", note="note one")
    create_idea(conn, "idea two")
    index_idea(conn, a["id"], embedder=embedder)
    b_id_ = b_id(conn, "idea two")
    index_idea(conn, b_id_, embedder=embedder)

    hits = find_duplicates(conn, "idea one again", "note one", embedder=embedder)
    assert [h["id"] for h in hits] == [a["id"]]
    assert hits[0]["score"] == pytest.approx(0.98, abs=0.01)

    # exclude_id hides the card being edited
    assert find_duplicates(conn, "idea one again", "note one",
                           embedder=embedder, exclude_id=a["id"]) == []


def test_find_duplicates_tunable_threshold(conn):
    embedder = FakeEmbedder({
        "a": [1.0, 0.0],
        "a again": [0.8, 0.6],     # cos 0.8
    })
    a = create_idea(conn, "a")
    index_idea(conn, a["id"], embedder=embedder)
    assert find_duplicates(conn, "a again", embedder=embedder) == []
    loose = find_duplicates(conn, "a again", embedder=embedder, threshold=0.75)
    assert [h["id"] for h in loose] == [a["id"]]


def test_find_duplicates_with_no_indexed_cards(conn):
    create_idea(conn, "only one")
    embedder = FakeEmbedder({"only one": [1.0, 0.0]})
    assert find_duplicates(conn, "anything", embedder=embedder) == []


def test_index_idea_missing_returns_false(conn):
    assert index_idea(conn, 999, embedder=FakeEmbedder({})) is False
