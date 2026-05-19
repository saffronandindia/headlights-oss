"""Email subject and body templates for the drafter agent.

Templates are pure functions of the prospect + their public work. No LLM
calls in v1 — keeps the output deterministic and the unit tests trivial.

When we swap to an LLM later, replace the body() function with a Claude
call but keep the same input/output shape so the rest of the pipeline is
unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

from marketing.github import GitHubRepo, GitHubUser

REPO_URL = "https://github.com/saffronandindia/headlights-oss"
TRACE_BASE_URL = "https://api.useheadlights.com/v1/sessions"  # stamped per-session


@dataclass(frozen=True)
class EmailDraft:
    """A full draft, ready for human review."""

    prospect_login: str
    to_address: str | None  # may be None if email isn't public
    subject: str
    body: str
    headers: dict[str, str]
    trace_session_id: str

    def to_eml(self) -> str:
        """Render as RFC 822-ish .eml format for human review."""
        header_lines = [
            f"To: {self.to_address or '(no public email)'}",
            f"Subject: {self.subject}",
        ]
        for k, v in self.headers.items():
            header_lines.append(f"{k}: {v}")
        return "\n".join(header_lines) + "\n\n" + self.body


def pick_signature_repo(repos: list[GitHubRepo]) -> GitHubRepo | None:
    """Choose the repo we'll reference in the email.

    Heuristic: most recently pushed, most starred, not a fork-looking name.
    """
    if not repos:
        return None
    candidates = [
        r
        for r in repos
        if not r.full_name.endswith("-fork")
        and r.stargazers_count >= 1
        and r.description
    ]
    if not candidates:
        candidates = list(repos)
    candidates.sort(key=lambda r: (r.stargazers_count, r.pushed_at), reverse=True)
    return candidates[0]


def subject_line(user: GitHubUser, signature_repo: GitHubRepo | None, target_library: str) -> str:
    """Generate an observational subject line. Concrete, specific, no exclamations."""
    if signature_repo:
        # "{repo_name} and the audit-log problem" style
        bare_name = signature_repo.full_name.split("/", 1)[1]
        return f"{bare_name} and the audit-log gap in agent systems"
    # Fall back to the library they starred
    return f"{target_library} starred — quick thought on agent audit logs"


def body_text(
    user: GitHubUser,
    signature_repo: GitHubRepo | None,
    target_library: str,
    trace_url: str,
) -> str:
    """Render the email body.

    Four short paragraphs:
    1. Reference one specific piece of their work
    2. The problem we're built around
    3. Live proof: the trace of the agent that wrote this email
    4. CTA: star the repo if interesting
    """
    display_name = user.name or user.login

    intro = _intro_paragraph(user, signature_repo, target_library)
    problem = _problem_paragraph()
    proof = _proof_paragraph(trace_url)
    cta = _cta_paragraph()

    return f"""Hi {display_name.split()[0]},

{intro}

{problem}

{proof}

{cta}

—
Eleanor Harris
Headlights · {REPO_URL}
"""


def _intro_paragraph(
    user: GitHubUser, signature_repo: GitHubRepo | None, target_library: str
) -> str:
    if signature_repo and signature_repo.description:
        # Specific: reference their actual repo
        return (
            f"I saw your work on {signature_repo.full_name} — "
            f"\"{signature_repo.description.strip().rstrip('.')}\" — "
            f"and it caught my eye because you also starred {target_library}, "
            "which is roughly the audience I'm trying to reach."
        )
    if signature_repo:
        return (
            f"I came across your repo {signature_repo.full_name} via the "
            f"{target_library} stargazer list."
        )
    return (
        f"I came across your profile via the {target_library} stargazer list — "
        "you're clearly building in the agent space."
    )


def _problem_paragraph() -> str:
    return (
        "Most AI-agent stacks today have an audit-log gap: when an agent does "
        "something the business needs to defend later, the existing records "
        "are database rows anyone with admin access can quietly modify. The "
        "EU AI Act Article 12 logging requirement is going to make that "
        "untenable for any agent operating in a regulated context."
    )


def _proof_paragraph(trace_url: str) -> str:
    return (
        "We're building Headlights to fix that — tamper-evident, "
        "cryptographically chained conduct records, open source, implementing "
        "the IETF AAT draft. The proof point I'll offer up front: this email "
        "itself was drafted by an agent we built, and every decision that "
        "agent made — including why I'm writing to you — is recorded in our "
        f"own chain. You can audit exactly what it did at: {trace_url}"
    )


def _cta_paragraph() -> str:
    return (
        "If you'd find any of this useful, the single most helpful thing "
        f"would be to star the repo: {REPO_URL}. No reply needed unless you "
        "want one — though I'd love to hear what you think."
    )


def draft_for(
    user: GitHubUser,
    user_repos: list[GitHubRepo],
    *,
    target_library: str,
    trace_session_id: str,
    trace_base_url: str = TRACE_BASE_URL,
) -> EmailDraft:
    """Produce a complete EmailDraft for a single prospect."""
    signature_repo = pick_signature_repo(user_repos)
    trace_url = f"{trace_base_url}/{trace_session_id}/trace"
    subject = subject_line(user, signature_repo, target_library)
    body = body_text(user, signature_repo, target_library, trace_url)
    return EmailDraft(
        prospect_login=user.login,
        to_address=user.email,
        subject=subject,
        body=body,
        headers={
            "X-Headlights-Trace": trace_url,
            "X-Headlights-Agent": "marketing-drafter-v0.1",
        },
        trace_session_id=trace_session_id,
    )
