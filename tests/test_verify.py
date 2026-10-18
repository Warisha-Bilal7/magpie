"""Planted-error tests for verify.unsupported_reasons (M2 issue #13).

The citation check is the product's credibility: these tests are the guard
against a coding agent quietly loosening it. Every failure mode from the
plan is planted here before verify.py exists.
"""

import pytest

from cdesk.verify import unsupported_reasons


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
