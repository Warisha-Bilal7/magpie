"""Planted-error tests for verify.unsupported_reasons (M2 issue #13).

The citation check is the product's credibility: these tests are the guard
against a coding agent quietly loosening it. Every failure mode from the
plan is planted here before verify.py exists.
"""

import pytest

from cdesk.verify import check_facts, check_rules, extract_facts, unsupported_reasons


@pytest.fixture
def by_id():
    return {
        1: {"id": 1, "title": "Deploy plan", "body": "Shipped v2 on 4 Nov, see https://example.com/r"},
        2: {"id": 2, "title": "Standup", "body": "Discussed the 142 failing tests with the team."},
        3: {"id": 3, "title": "Notes", "body": "No digits or links here."},
    }


def test_clean_line_has_no_reasons(by_id):
    line = {"text": "Shipped v2 on 4 Nov, see https://example.com/r", "cites": [1]}
    assert unsupported_reasons(line, by_id) == []


def test_clean_line_plain_text(by_id):
    line = {"text": "Discussed the failing tests with the team.", "cites": [2]}
    assert unsupported_reasons(line, by_id) == []


def test_missing_citation(by_id):
    line = {"text": "Did a thing", "cites": []}
    assert "no citation" in unsupported_reasons(line, by_id)


def test_cites_unknown_capture_id(by_id):
    line = {"text": "Did a thing", "cites": [99]}
    assert "cites an unknown capture id" in unsupported_reasons(line, by_id)


def test_invented_number(by_id):
    line = {"text": "Closed 99 tickets on 4 Nov", "cites": [1]}
    reasons = unsupported_reasons(line, by_id)
    assert any("number 99" in r for r in reasons)


def test_invented_url(by_id):
    line = {"text": "Details at https://not-in-source.example/x", "cites": [3]}
    reasons = unsupported_reasons(line, by_id)
    assert any("url" in r for r in reasons)


def test_number_substring_does_not_count(by_id):
    # "42" must not be excused by "142" appearing in the source
    line = {"text": "42 tests failed", "cites": [2]}
    reasons = unsupported_reasons(line, by_id)
    assert any("number 42" in r for r in reasons)


def test_exact_number_with_punctuation_matches(by_id):
    line = {"text": "142 failing tests", "cites": [2]}
    assert unsupported_reasons(line, by_id) == []


def test_trailing_punctuation_stripped_from_url(by_id):
    line = {"text": "See https://example.com/r.", "cites": [1]}
    assert unsupported_reasons(line, by_id) == []


def test_multiple_reasons_collected(by_id):
    line = {"text": "Closed 99 tickets, see https://fake.example/", "cites": [1]}
    reasons = unsupported_reasons(line, by_id)
    assert len(reasons) >= 2


def test_cites_across_multiple_captures(by_id):
    line = {"text": "Shipped v2 and closed 99 tickets", "cites": [1, 2]}
    reasons = unsupported_reasons(line, by_id)
    assert any("number 99" in r for r in reasons)


def test_date_fragment_numbers_checked(by_id):
    line = {"text": "Meeting moved to 4 Nov", "cites": [3]}
    reasons = unsupported_reasons(line, by_id)
    assert any("number 4" in r for r in reasons)


def test_single_digit_source_number_matches(by_id):
    line = {"text": "Shipped v2 on 4 Nov", "cites": [1]}
    assert unsupported_reasons(line, by_id) == []


# ---------- drafts: extract_facts (M4 issue #25) ----------------------------

def test_extract_facts_day_month():
    assert "date:4-nov" in extract_facts("Shipped on 4 Nov.")
    assert "date:4-nov" in extract_facts("Shipped on Nov 4.")
    assert "date:4-nov" in extract_facts("Shipped on 4th November")


def test_extract_facts_month_day_with_period():
    assert "date:1-dec" in extract_facts("starts Dec. 1")


def test_extract_facts_time():
    assert "time:3:30pm" in extract_facts("at 3:30 PM")
    assert "time:9:00am" in extract_facts("at 9am")
    assert "time:12:15pm" in extract_facts("at 12:15pm")


def test_extract_facts_url_normalized():
    assert "url:https://example.com/x" in extract_facts("See https://example.com/x.")
    assert "url:https://example.com/x" in extract_facts("See HTTPS://Example.com/X")


def test_extract_facts_handle_lowercased():
    assert "handle:@alice" in extract_facts("cc @Alice")


def test_extract_facts_numbers():
    assert "num:142" in extract_facts("142 tests")
    assert "num:500" in extract_facts("1,500 users")    # regex sees the digit groups
    assert not any(f.startswith("num:2") for f in extract_facts("v2 release"))  # v2 is not a number
    assert not any(f.startswith("num:4") for f in extract_facts("on 4 Nov"))    # single digits are not facts


def test_extract_facts_empty():
    assert extract_facts("no digits dates or links here") == set()


# ---------- drafts: check_facts (M4 issue #25) ------------------------------

SOURCE = "Workshop on 4 Nov at 3:30 pm. Register at https://example.com/w. cc @alice. 142 seats left."


def test_check_facts_clean_draft_passes():
    assert check_facts("Join the workshop on 4 Nov at 3:30 pm.", SOURCE) == []


def test_check_facts_invented_date():
    reasons = check_facts("Workshop moved to 14 Nov.", SOURCE)
    # "14" is also caught as an invented number — stricter than needed, by design
    assert "not in source: 14-nov" in reasons
    assert "not in source: 14" in reasons


def test_check_facts_invented_time():
    reasons = check_facts("Starts at 5:00 pm sharp.", SOURCE)
    assert reasons == ["not in source: 5:00pm"]


def test_check_facts_invented_url():
    reasons = check_facts("Register at https://phish.example/login", SOURCE)
    assert any("phish.example" in r for r in reasons)


def test_check_facts_invented_handle_and_number():
    reasons = check_facts("cc @mallory — 99 seats left", SOURCE)
    assert any("@mallory" in r for r in reasons)
    assert any("99" in r for r in reasons)


def test_check_facts_multiple_missing_sorted():
    reasons = check_facts("On 14 Nov at 5:00 pm, 99 seats.", SOURCE)
    assert len(reasons) == 4
    assert any("14-nov" in r for r in reasons)
    assert any("5:00pm" in r for r in reasons)
    assert any("99" in r for r in reasons)


# ---------- drafts: check_rules (M4 issue #26) ------------------------------

RULES = {"max_chars": 50, "max_hashtags": 2, "banned": ["game-changer", "I'm thrilled"]}


def test_check_rules_clean_draft_passes():
    assert check_rules("Short honest post about shipping.", RULES) == []


def test_check_rules_too_long():
    draft = "x" * 51
    reasons = check_rules(draft, RULES)
    assert any(r.startswith("too long: 51 > 50") for r in reasons)


def test_check_rules_too_many_hashtags():
    reasons = check_rules("ok #a #b #c", RULES)
    assert any("too many hashtags: 3 > 2" in r for r in reasons)


def test_check_rules_banned_phrase_case_insensitive():
    reasons = check_rules("This release is a Game-Changer.", RULES)
    assert "contains banned phrase: game-changer" in reasons


def test_check_rules_default_limits_when_keys_missing():
    assert check_rules("plain text", {}) == []
    reasons = check_rules("#" + "a" * 40 + " #b #c #d #e #f #g #h #i #j #k", {"max_hashtags": 10})
    assert any("too many hashtags" in r for r in reasons)


def test_check_rules_collects_all_violations():
    draft = "x" * 60 + " #a #b #c game-changer"
    reasons = check_rules(draft, RULES)
    assert len(reasons) == 3
