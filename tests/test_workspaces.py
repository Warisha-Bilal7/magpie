"""Workspace CRUD, rules and past-post corpus tests (M3 #18, #19, #22)."""

import json

import pytest

from cdesk.workspaces import (
    add_banned_phrase,
    add_past_post,
    create_workspace,
    effective_rules,
    get_workspace,
    list_past_posts,
    list_workspaces,
    remove_banned_phrase,
    update_workspace,
)


@pytest.fixture
def conn():
    from cdesk.db import init_db
    c = init_db(":memory:")
    yield c
    c.close()


def test_create_and_get(conn):
    w = create_workspace(conn, "LinkedIn", kind="linkedin", cadence_days=3,
                         audience="Recruiters and devs")
    assert w["id"] > 0
    fetched = get_workspace(conn, w["id"])
    assert fetched["name"] == "LinkedIn"
    assert fetched["kind"] == "linkedin"
    assert fetched["cadence_days"] == 3
    assert get_workspace(conn, name="LinkedIn")["id"] == w["id"]


def test_create_duplicate_name_rejected(conn):
    create_workspace(conn, "Substack", kind="substack")
    with pytest.raises(ValueError):
        create_workspace(conn, "Substack", kind="substack")


def test_bad_kind_rejected(conn):
    with pytest.raises(ValueError):
        create_workspace(conn, "X", kind="not-a-kind")


def test_list_and_update_and_delete(conn):
    w1 = create_workspace(conn, "A", kind="personal")
    create_workspace(conn, "B", kind="society")
    assert len(list_workspaces(conn)) == 2
    update_workspace(conn, w1["id"], cadence_days=14, audience="friends")
    w1b = get_workspace(conn, w1["id"])
    assert w1b["cadence_days"] == 14
    assert w1b["audience"] == "friends"
    from cdesk.workspaces import delete_workspace
    delete_workspace(conn, w1["id"])
    assert get_workspace(conn, w1["id"]) is None


def test_effective_rules_use_platform_defaults(conn):
    w = create_workspace(conn, "LI", kind="linkedin")
    rules = effective_rules(w)
    assert rules["max_chars"] == 3000
    assert "i'm thrilled" in rules["banned"]


def test_stored_rules_override_defaults(conn):
    w = create_workspace(conn, "LI2", kind="linkedin",
                         rules={"max_chars": 500, "banned": ["nope"]})
    rules = effective_rules(w)
    assert rules["max_chars"] == 500
    assert rules["banned"] == ["nope"]
    assert rules["max_hashtags"] == 5  # default kept


def test_banned_phrase_add_remove(conn):
    w = create_workspace(conn, "Society", kind="society")
    add_banned_phrase(conn, w["id"], "game-changer")
    rules = effective_rules(get_workspace(conn, w["id"]))
    assert "game-changer" in rules["banned"]
    remove_banned_phrase(conn, w["id"], "game-changer")
    rules = effective_rules(get_workspace(conn, w["id"]))
    assert "game-changer" not in rules["banned"]


def test_banned_phrase_dedupe_case_insensitive(conn):
    w = create_workspace(conn, "P", kind="personal")
    add_banned_phrase(conn, w["id"], "Thrilled")
    add_banned_phrase(conn, w["id"], "thrilled")
    banned = effective_rules(get_workspace(conn, w["id"]))["banned"]
    assert banned.count("thrilled") == 1


def test_past_post_roundtrip(conn):
    w = create_workspace(conn, "Sub", kind="substack")
    pid = add_past_post(conn, w["id"], "My first essay about compilers.",
                        url="https://example.com/1", published_at="2026-01-01")
    posts = list_past_posts(conn, w["id"])
    assert len(posts) == 1
    assert posts[0]["id"] == pid
    assert posts[0]["url"] == "https://example.com/1"


def test_past_posts_isolated_per_workspace(conn):
    a = create_workspace(conn, "A", kind="personal")
    b = create_workspace(conn, "B", kind="personal")
    add_past_post(conn, a["id"], "only in A")
    assert list_past_posts(conn, b["id"]) == []


def test_import_posts_text_separator(conn):
    w = create_workspace(conn, "LI", kind="linkedin")
    from cdesk.workspaces import parse_posts_text
    text = "First post body\n---\nSecond post body\n---\n\n"
    posts = parse_posts_text(text)
    assert [p["body"] for p in posts] == ["First post body", "Second post body"]


def test_import_posts_json(conn):
    from cdesk.workspaces import parse_posts_json
    data = [{"body": "a", "url": "u1"}, {"body": "b"}]
    posts = parse_posts_json(json.dumps(data))
    assert posts[0]["url"] == "u1"
    assert posts[1]["body"] == "b"


def test_parse_posts_text_tolerates_utf8_bom():
    from cdesk.workspaces import parse_posts_text
    posts = parse_posts_text("\ufeffFirst post\n---\nSecond post")
    assert [p["body"] for p in posts] == ["First post", "Second post"]
