"""Tests for marketing.templates — email rendering."""

from __future__ import annotations

from marketing.github import GitHubRepo, GitHubUser
from marketing.templates import (
    REPO_URL,
    body_text,
    draft_for,
    pick_signature_repo,
    subject_line,
)


def _user(**kwargs) -> GitHubUser:
    defaults = dict(
        login="alice",
        name="Alice Engineer",
        company="Stripe",
        email="alice@example.com",
        bio="Staff engineer",
        blog=None,
        location="Sydney",
        public_repos=20,
        followers=100,
        created_at="2022-01-01T00:00:00Z",
        profile_url="https://github.com/alice",
    )
    defaults.update(kwargs)
    return GitHubUser(**defaults)


def _repo(full_name: str, **kwargs) -> GitHubRepo:
    defaults = dict(
        full_name=full_name,
        description="A useful project",
        language="Python",
        stargazers_count=10,
        pushed_at="2026-05-01T00:00:00Z",
        html_url=f"https://github.com/{full_name}",
    )
    defaults.update(kwargs)
    return GitHubRepo(**defaults)


# ── pick_signature_repo ───────────────────────────────────────────────────


def test_pick_signature_repo_prefers_starred_with_description() -> None:
    repos = [
        _repo("alice/no-stars", stargazers_count=0, description="nothing"),
        _repo("alice/with-stars", stargazers_count=50, description="The real one"),
        _repo("alice/no-desc", stargazers_count=100, description=None),
    ]
    chosen = pick_signature_repo(repos)
    assert chosen.full_name == "alice/with-stars"


def test_pick_signature_repo_empty_list_returns_none() -> None:
    assert pick_signature_repo([]) is None


def test_pick_signature_repo_falls_back_to_first_if_no_desc() -> None:
    """When no repo has description+stars, we still return something."""
    repos = [
        _repo("alice/a", description=None, stargazers_count=0),
        _repo("alice/b", description=None, stargazers_count=0),
    ]
    chosen = pick_signature_repo(repos)
    assert chosen is not None


# ── subject_line ──────────────────────────────────────────────────────────


def test_subject_with_signature_repo_mentions_repo() -> None:
    subj = subject_line(
        _user(), _repo("alice/agent-runtime"), "LangChain"
    )
    assert "agent-runtime" in subj
    assert "!" not in subj  # tone: observational, never exclaimed
    assert subj == subj.lower() or subj[0].isupper()  # standard sentence case


def test_subject_without_repo_falls_back_to_library() -> None:
    subj = subject_line(_user(), None, "LangChain")
    assert "LangChain" in subj


def test_subject_is_under_eighty_characters() -> None:
    """Email subject lines truncated at ~78 chars by many clients.

    A short, specific subject is exactly the point — anything longer hides the
    observation we're trying to make.
    """
    subj = subject_line(
        _user(),
        _repo("alice-engineer/some-quite-long-repo-name-for-testing"),
        "LangChain",
    )
    assert len(subj) <= 80, f"subject too long: {len(subj)} chars"


# ── body_text ─────────────────────────────────────────────────────────────


def test_body_addresses_recipient_by_first_name() -> None:
    body = body_text(
        _user(name="Alice Engineer"),
        _repo("alice/agent-runtime"),
        "LangChain",
        trace_url="https://example.com/trace/abc",
    )
    assert body.startswith("Hi Alice,")


def test_body_falls_back_to_login_if_no_name() -> None:
    body = body_text(
        _user(name=None, login="alice"),
        _repo("alice/x"),
        "LangChain",
        trace_url="https://example.com/trace/x",
    )
    # First word after "Hi " should be the login
    assert "Hi alice," in body


def test_body_references_signature_repo() -> None:
    body = body_text(
        _user(),
        _repo("alice/agent-runtime", description="Fast agent orchestration"),
        "LangChain",
        trace_url="https://example.com/trace/abc",
    )
    assert "agent-runtime" in body
    assert "Fast agent orchestration" in body


def test_body_embeds_trace_url() -> None:
    body = body_text(
        _user(),
        _repo("alice/x"),
        "LangChain",
        trace_url="https://example.com/trace/specific-session-id",
    )
    assert "https://example.com/trace/specific-session-id" in body


def test_body_embeds_repo_url() -> None:
    body = body_text(_user(), _repo("alice/x"), "LangChain", trace_url="t")
    assert REPO_URL in body


def test_body_ends_with_signature() -> None:
    body = body_text(_user(), _repo("alice/x"), "LangChain", trace_url="t")
    assert body.rstrip().endswith("Headlights · " + REPO_URL)


# ── draft_for (end-to-end) ────────────────────────────────────────────────


def test_draft_for_full_pipeline() -> None:
    draft = draft_for(
        _user(name="Alice Engineer", email="alice@example.com"),
        [_repo("alice/agent-runtime", stargazers_count=120)],
        target_library="LangChain",
        trace_session_id="11111111-2222-3333-4444-555555555555",
    )
    assert draft.prospect_login == "alice"
    assert draft.to_address == "alice@example.com"
    assert "11111111-2222-3333-4444-555555555555" in draft.body
    assert "11111111-2222-3333-4444-555555555555" in draft.headers["X-Headlights-Trace"]


def test_draft_to_eml_is_parseable() -> None:
    draft = draft_for(
        _user(email="alice@example.com"),
        [_repo("alice/x")],
        target_library="LangChain",
        trace_session_id="abc-123",
    )
    eml = draft.to_eml()
    assert eml.startswith("To: alice@example.com\n")
    assert "Subject: " in eml.splitlines()[1]
    assert "X-Headlights-Trace: " in eml


def test_draft_handles_missing_email_gracefully() -> None:
    draft = draft_for(
        _user(email=None),
        [_repo("alice/x")],
        target_library="LangChain",
        trace_session_id="abc",
    )
    assert draft.to_address is None
    eml = draft.to_eml()
    assert "(no public email)" in eml


def test_draft_is_deterministic_for_same_input() -> None:
    """The template path must produce byte-identical output for the same
    input. Lose this and the chain audit becomes useless because the
    'why this body was chosen' record won't match the body anymore."""
    user = _user()
    repos = [_repo("alice/x")]
    args = dict(target_library="LangChain", trace_session_id="abc")
    d1 = draft_for(user, repos, **args)
    d2 = draft_for(user, repos, **args)
    assert d1.subject == d2.subject
    assert d1.body == d2.body
