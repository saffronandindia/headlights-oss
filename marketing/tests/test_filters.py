"""Tests for marketing.filters — pure prospect-classification logic."""

from __future__ import annotations

from marketing.filters import (
    NEGATIVE_BIO_TOKENS,
    POSITIVE_BIO_TOKENS,
    account_is_mature,
    bio_signals,
    classify,
    has_b2b_company,
    has_minimum_repos,
)
from marketing.github import GitHubUser


def _user(**kwargs) -> GitHubUser:
    defaults = dict(
        login="testuser",
        name="Test User",
        company=None,
        email=None,
        bio=None,
        blog=None,
        location=None,
        public_repos=10,
        followers=50,
        created_at="2022-01-01T00:00:00Z",
        profile_url="https://github.com/testuser",
    )
    defaults.update(kwargs)
    return GitHubUser(**defaults)


def test_no_company_fails() -> None:
    r = has_b2b_company(_user(company=None))
    assert r.passed is False
    assert r.score == 0


def test_company_with_b2b_hint_scores_high() -> None:
    r = has_b2b_company(_user(company="Acme Labs Pty Ltd"))
    assert r.passed is True
    assert r.score == 3


def test_plain_company_name_still_passes() -> None:
    r = has_b2b_company(_user(company="Google"))
    assert r.passed is True
    assert r.score == 2


def test_company_with_at_prefix_normalised() -> None:
    r = has_b2b_company(_user(company="@stripe"))
    assert r.passed is True


def test_below_threshold_fails() -> None:
    r = has_minimum_repos(_user(public_repos=2))
    assert r.passed is False


def test_at_threshold_passes() -> None:
    r = has_minimum_repos(_user(public_repos=5))
    assert r.passed is True


def test_no_bio_is_neutral() -> None:
    r = bio_signals(_user(bio=None))
    assert r.passed is True
    assert r.score == 0


def test_negative_bio_token_rejects() -> None:
    r = bio_signals(_user(bio="CS student"))
    assert r.passed is False
    assert "student" in r.reason


def test_positive_bio_tokens_lift_score() -> None:
    r = bio_signals(_user(bio="Staff engineer working on agent infrastructure"))
    assert r.passed is True
    assert r.score > 0


def test_neutral_bio_passes_with_zero_score() -> None:
    r = bio_signals(_user(bio="I like dogs."))
    assert r.passed is True
    assert r.score == 0


def test_negative_signal_short_circuits_positive() -> None:
    r = bio_signals(_user(bio="CS student aspiring to be an engineer"))
    assert r.passed is False


def test_classify_full_b2b_prospect_is_kept() -> None:
    verdict = classify(_user(
        company="Stripe", bio="Staff engineer building infra",
        public_repos=42, followers=300,
    ))
    assert verdict.is_prospect is True
    assert verdict.score >= 4


def test_classify_student_is_filtered() -> None:
    verdict = classify(_user(
        company="University", bio="CS student", public_repos=8, followers=10,
    ))
    assert verdict.is_prospect is False
    assert any("student" in r for r in verdict.reasons)


def test_classify_thin_account_is_filtered() -> None:
    verdict = classify(_user(
        company=None, bio=None, public_repos=2, followers=1,
    ))
    assert verdict.is_prospect is False


def test_classify_reasons_list_matches_check_count() -> None:
    verdict = classify(_user(
        company="Acme", bio=None, public_repos=10,
    ))
    assert len(verdict.reasons) == 4


def test_account_is_mature_doesnt_block_low_followers() -> None:
    r = account_is_mature(_user(followers=0))
    assert r.passed is True


def test_no_overlap_between_positive_and_negative_tokens() -> None:
    overlap = set(NEGATIVE_BIO_TOKENS) & set(POSITIVE_BIO_TOKENS)
    assert overlap == set(), f"tokens appear in both lists: {overlap}"
