"""Upload step — close the email-as-demo loop.

Reads the per-draft chains produced by `marketing.drafter`, replays each
one as a session on the Headlights server, publishes the session, and
rewrites the corresponding .eml file to embed the real trace URL.

Before upload, .eml files contain a placeholder trace URL pointing at
the local trace_session_id used to seed the chain. After upload, the
trace URL points at the server-side session_id, which is the one a
recipient will actually be able to visit and verify.

CLI:

    python -m marketing.upload \\
        --drafts-dir drafts/ \\
        --server-url http://localhost:8080 \\
        --agent-id urn:headlights:agent:marketing-drafter \\
        --api-key hl_live_...

Idempotency: re-running on the same drafts/ overwrites the .eml's trace
URL with the latest upload's URL. The previous server session remains
published but unreferenced. Don't re-run unless you mean to.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from headlights_chain.enums import ActionType, Outcome, TrustLevel
from headlights_sdk.hosted import HostedClient, HostedClientError


@dataclasses.dataclass(frozen=True)
class UploadResult:
    """Outcome of uploading one per-draft chain."""

    local_trace_session_id: str
    server_session_id: str
    trace_url: str
    eml_path: Path | None  # may be None if no matching .eml found


# ── Public API ───────────────────────────────────────────────────────────


def upload_chain(
    *,
    chain_records: list[dict[str, Any]],
    client: HostedClient,
    local_trace_session_id: str,
) -> tuple[str, str]:
    """Replay a local chain onto the server as a new session, publish it,
    and return (server_session_id, server_trace_url).

    Lifecycle records (genesis, session_end) are NOT replayed individually;
    the server constructs its own genesis when we open the session, and its
    own session_end when we close.
    """
    if not chain_records:
        raise ValueError("empty chain — nothing to upload")

    # Build genesis_detail that references the local chain we're replaying.
    genesis_detail = {
        "uploaded_from": "marketing.upload",
        "local_trace_session_id": local_trace_session_id,
    }

    with client.session(genesis_detail=genesis_detail):
        # Replay each non-lifecycle record as an /actions POST.
        for record in chain_records:
            if record.get("action_type") == ActionType.LIFECYCLE.value:
                continue  # skip session_start / session_end
            client._post_action(
                action_type=ActionType(record["action_type"]),
                action_detail=record.get("action_detail") or {},
                outcome=Outcome(record.get("outcome", "success")),
                trust_level=TrustLevel(record.get("trust_level", "L1")),
            )

        server_session_id = client.session_id
        assert server_session_id is not None
    # Session auto-closes on context-manager exit.

    client.publish_session(server_session_id, public=True)
    trace_url = f"{client.api_url}/v1/sessions/{server_session_id}/trace"
    return server_session_id, trace_url


def rewrite_eml_trace_url(
    *,
    eml_path: Path,
    old_trace_url_fragment: str,
    new_trace_url: str,
) -> bool:
    """Find `*old_trace_url_fragment*` in the .eml's body or headers and
    replace it with `new_trace_url`. Returns True if a replacement happened.

    Matches the literal token rather than the full URL because the eml may
    have been wrapped or re-flowed in some clients.
    """
    text = eml_path.read_text(encoding="utf-8")
    if old_trace_url_fragment not in text:
        return False
    # Replace the entire matching URL substring. We assume the URL in the
    # .eml has the form `<some-base>/<old_trace_url_fragment>` or similar
    # — find each occurrence and replace just the URL.
    new_text = _replace_trace_urls(text, old_trace_url_fragment, new_trace_url)
    eml_path.write_text(new_text, encoding="utf-8")
    return True


def _replace_trace_urls(text: str, fragment: str, new_url: str) -> str:
    """Replace any URL containing `fragment` with `new_url`.

    A "URL" here is any whitespace-delimited token containing `fragment`.
    """
    parts = []
    for token in text.split():
        if fragment in token:
            # Strip trailing punctuation (period, comma, paren) so we keep it
            # attached to the new URL.
            trailing = ""
            while token and token[-1] in ".,);":
                trailing = token[-1] + trailing
                token = token[:-1]
            parts.append(new_url + trailing)
        else:
            parts.append(token)
    # Note: re-joining with " " loses the original whitespace. Use a smarter
    # approach: do a linear replace over each whitespace-delimited URL.
    return _replace_preserving_whitespace(text, fragment, new_url)


def _replace_preserving_whitespace(text: str, fragment: str, new_url: str) -> str:
    """Replace each whitespace-delimited token containing `fragment` with
    `new_url`, preserving original whitespace between tokens."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        # Skip whitespace
        while i < n and text[i].isspace():
            out.append(text[i])
            i += 1
        # Read next non-whitespace token
        start = i
        while i < n and not text[i].isspace():
            i += 1
        token = text[start:i]
        if fragment in token:
            trailing = ""
            while token and token[-1] in ".,);":
                trailing = token[-1] + trailing
                token = token[:-1]
            out.append(new_url + trailing)
        else:
            out.append(token)
    return "".join(out)


def upload_all(
    *,
    drafts_dir: Path,
    client: HostedClient,
) -> list[UploadResult]:
    """Upload every chain in `drafts_dir/chains/` and rewrite the matching .eml.

    Returns one UploadResult per chain processed.
    """
    chains_dir = drafts_dir / "chains"
    if not chains_dir.exists():
        raise FileNotFoundError(f"no chains/ subdirectory in {drafts_dir}")

    eml_files = list(drafts_dir.glob("*.eml"))
    results: list[UploadResult] = []

    for chain_path in sorted(chains_dir.glob("*.json")):
        local_trace_session_id = chain_path.stem  # filename is `{uuid}.json`
        chain_records = json.loads(chain_path.read_text(encoding="utf-8"))

        server_sid, trace_url = upload_chain(
            chain_records=chain_records,
            client=client,
            local_trace_session_id=local_trace_session_id,
        )

        # Find the matching .eml. Search for the local trace_session_id in
        # the .eml's body — that's the placeholder URL we stamped at draft
        # time.
        eml_match: Path | None = None
        for eml in eml_files:
            if local_trace_session_id in eml.read_text(encoding="utf-8"):
                eml_match = eml
                break
        if eml_match is not None:
            rewrite_eml_trace_url(
                eml_path=eml_match,
                old_trace_url_fragment=local_trace_session_id,
                new_trace_url=trace_url,
            )

        results.append(
            UploadResult(
                local_trace_session_id=local_trace_session_id,
                server_session_id=server_sid,
                trace_url=trace_url,
                eml_path=eml_match,
            )
        )

    # Write a manifest for traceability.
    manifest_path = drafts_dir / "uploaded.json"
    manifest_path.write_text(
        json.dumps(
            [dataclasses.asdict(r) | {"eml_path": str(r.eml_path) if r.eml_path else None} for r in results],
            indent=2,
        ),
        encoding="utf-8",
    )
    return results


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marketing.upload")
    parser.add_argument("--drafts-dir", type=Path, default=Path("drafts"))
    parser.add_argument(
        "--server-url",
        type=str,
        default=os.environ.get("HEADLIGHTS_SERVER_URL", "http://localhost:8080"),
    )
    parser.add_argument(
        "--agent-id",
        type=str,
        default=os.environ.get("HEADLIGHTS_AGENT_ID"),
        help="Server-side agent identity. Required.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("HEADLIGHTS_API_KEY"),
        help="API key for the agent. Required.",
    )
    parser.add_argument(
        "--agent-version", type=str, default="0.1.0",
    )
    args = parser.parse_args(argv)

    if not args.agent_id or not args.api_key:
        print(
            "error: --agent-id and --api-key (or HEADLIGHTS_AGENT_ID / HEADLIGHTS_API_KEY) required",
            file=sys.stderr,
        )
        return 2

    client = HostedClient(
        api_url=args.server_url,
        api_key=args.api_key,
        agent_id=args.agent_id,
        agent_version=args.agent_version,
    )
    try:
        results = upload_all(drafts_dir=args.drafts_dir, client=client)
    except HostedClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(f"Uploaded {len(results)} draft chains.")
    for r in results:
        eml = r.eml_path.name if r.eml_path else "(no .eml match)"
        print(f"  {r.local_trace_session_id[:8]}… → {r.server_session_id[:8]}…  ({eml})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
