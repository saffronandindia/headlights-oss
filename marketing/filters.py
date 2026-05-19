"""B2B context detection — does this GitHub user look like a real B2B prospect?

The bar is deliberately practical, not perfect. We are filtering to remove
obvious students, hobbyists, and dormant accounts. False negatives are fine —
losing a prospect is cheap. False positives are expensive — emailing a 17-year-old
student is the failure mode we explicitly avoid.

Each filter returns (passed, reason) so the discovery agent can record exactly
why a prospect was kept or dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from marketing.github import GitHubUser

# Soft negative signals — words that suggest student/hobbyist context
NEGATIVE_BIO_TOKENS = {
    "student",
    "self-taught",
    "self taught",
    "aspiring",
    "learning",
    "newbie",
    "high school",
    "bootcamp",
    "junior dev",
    "career switcher",
    "looking for my first",
}

# Positive signals — phrases that lift confidence
POSITIVE_BIO_TOKENS = {
    "engineer",
    "developer",
    "founder",
    "cto",
    "vp",
    "head of",
    "principal",
    "staff",
    "lead",
    "architect",
    "platform",
    "infrastructure",
    "ml",
    "machine learning",
    "ai",
    "agents",
}

# Companies that are obviously B2B even if the rest of the profile is thin
KNOWN_B2B_COMPANY_HINTS = ("inc", "ltd", "gmbh", "pty", "llc", "labs", "ai", ".com")


@dataclass(frozen=True)
class FilterResult:
    """Outcome of a single filter check."""

    passed: bool
    reason: str
    score: int = 0


@dataclass(frozen=True)
class ProspectVerdict:
    """Aggregate result across all filters."""

    is_prospect: bool
    score: int
    reasons: list[str]


def has_b2b_company(user: GitHubUser) -> FilterResult:
    if not user.company:
        return FilterResult(False, "no company field", 0)
    company_lower = user.company.lower().strip().lstrip("@")
    if any(hint in company_lower for hint in KNOWN_B2B_COMPANY_HINTS):
        return FilterResult(True, f"company looks B2B: {user.company}", 3)
    # Plain company name (e.g. "google", "stripe") still counts
    return FilterResult(True, f"company set: {user.company}", 2)


def has_minimum_repos(user: GitHubUser, *, threshold: int = 5) -> FilterResult:
    if user.public_repos < threshold:
        return FilterResult(False, f"only {user.public_repos} public repos", 0)
    return FilterResult(True, f"{user.public_repos} public repos", 1)


def bio_signals(user: GitHubUser) -> FilterResult:
    if not user.bio:
        return FilterResult(True, "no bio (neutral)", 0)
    bio_lower = user.bio.lower()
    if any(token in bio_lower for token in NEGATIVE_BIO_TOKENS):
        matched = next(t for t in NEGATIVE_BIO_TOKENS if t in bio_lower)
        return FilterResult(False, f"bio contains negative signal: '{matched}'", -3)
    positive_hits = [t for t in POSITIVE_BIO_TOKENS if t in bio_lower]
    if positive_hits:
        return FilterResult(True, f"bio positive signals: {positive_hits[:3]}", 2)
    return FilterResult(True, "bio neutral", 0)


def account_is_mature(user: GitHubUser, *, min_followers: int = 5) -> FilterResult:
    """A wobbly proxy for 'is this account at least somewhat established.'

    We don't require many followers — just not a literal zero. Zero followers
    plus zero company plus zero bio is the deletable-bot signature.
    """
    if user.followers < min_followers:
        return FilterResult(True, f"followers={user.followers} (low but allowed)", 0)
    return FilterResult(True, f"{user.followers} followers", 1)


def classify(user: GitHubUser) -> ProspectVerdict:
    """Run all filters; return the aggregate verdict.

    Rules:
    - Any HARD failure (passed=False) below disqualifies the prospect.
    - Score is the sum of all filter scores; used downstream to rank.
    """
    checks = [
        has_b2b_company(user),
        has_minimum_repos(user),
        bio_signals(user),
        account_is_mature(user),
    ]
    is_prospect = all(check.passed for check in checks)
    total_score = sum(check.score for check in checks)
    reasons = [check.reason for check in checks]
    return ProspectVerdict(is_prospect=is_prospect, score=total_score, reasons=reasons)
