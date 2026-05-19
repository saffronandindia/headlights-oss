"""Public trace viewer + session publishing.

The trace viewer is the artifact that goes in every outbound email: a public
HTML page rendering exactly what an agent did in one session, with a button
to download the canonical export for offline verification via
`pip install headlights-verify`.

Sessions are private by default. An agent owner explicitly opts in to public
view by POSTing to /publish. Once published, anyone with the URL can audit
the session without authentication.

The split serves two product goals:

- Email-as-demo. The same URL embedded in every outreach email shows the
  recipient exactly what the agent that wrote to them did. The proof and the
  pitch are the same artifact.
- Regulator-friendly default. Sessions are not accidentally exposed. Going
  public requires a deliberate action and is itself a chain-recordable
  decision.
"""

from __future__ import annotations

import html
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import HTMLResponse, JSONResponse

from headlights_chain import Chain
from headlights_chain.canonical import record_hash_for_chain
from headlights_chain.signatures import VerifyingKey
from headlights_server.deps import get_store, require_api_key_for_agent
from headlights_server.models import (
    PublishSessionRequest,
    PublishSessionResponse,
)
from headlights_server.storage import Store

router = APIRouter(tags=["trace"])


# ── Publish endpoint (authenticated) ─────────────────────────────────────


@router.post(
    "/v1/agents/{agent_id}/sessions/{session_id}/publish",
    response_model=PublishSessionResponse,
    summary="Toggle public-trace view for a session.",
)
def publish_session_endpoint(
    body: PublishSessionRequest,
    agent_id: Annotated[str, Depends(require_api_key_for_agent)],
    session_id: Annotated[str, Path()],
    store: Annotated[Store, Depends(get_store)],
) -> PublishSessionResponse:
    session = store.get_session(session_id)
    if session is None or session.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

    store.set_session_public_view(session_id, body.public)
    return PublishSessionResponse(
        session_id=session_id,
        public=body.public,
        trace_url=f"/v1/sessions/{session_id}/trace",
    )


# ── Public trace view (unauthenticated) ──────────────────────────────────


@router.get(
    "/v1/sessions/{session_id}/trace",
    response_class=HTMLResponse,
    summary="Public HTML trace of a published session. No auth required.",
)
def trace_html_endpoint(
    session_id: Annotated[str, Path()],
    store: Annotated[Store, Depends(get_store)],
) -> HTMLResponse:
    session = store.get_session(session_id)
    if session is None or not session.public_view:
        # Identical 404 for "doesn't exist" and "exists but not published"
        # so a public URL can't be used to enumerate private session_ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")

    agent = store.get_agent(session.agent_id)
    records = store.get_session_records(session_id)
    verification = _verify(records, agent.public_key_pem if agent else None)

    html_body = _render_trace_html(
        agent_id=session.agent_id,
        agent_name=agent.agent_name if agent else session.agent_id,
        session=session,
        records=records,
        verification=verification,
    )
    return HTMLResponse(content=html_body)


@router.get(
    "/v1/sessions/{session_id}/trace.json",
    summary="Canonical JSON export of a published session. Feeds headlights-verify.",
)
def trace_json_endpoint(
    session_id: Annotated[str, Path()],
    store: Annotated[Store, Depends(get_store)],
) -> JSONResponse:
    session = store.get_session(session_id)
    if session is None or not session.public_view:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")

    records = store.get_session_records(session_id)
    return JSONResponse(
        content=records,
        headers={
            "Content-Disposition": f'attachment; filename="trace-{session_id}.json"',
        },
    )


# ── Internals ────────────────────────────────────────────────────────────


def _verify(records: list[dict[str, Any]], public_key_pem: str | None) -> dict[str, Any]:
    """Run the chain primitive's verify(). Returns a small dict for the HTML."""
    if not records:
        return {"is_intact": False, "reason": "empty trace", "failed_position": None}
    try:
        chain = Chain.from_records(records)
        verifying_key = (
            VerifyingKey.from_pem(public_key_pem.encode("utf-8"))
            if public_key_pem
            else None
        )
        result = chain.verify(verifying_key=verifying_key)
        return {
            "is_intact": result.is_intact,
            "reason": result.reason,
            "failed_position": result.failed_position,
            "signature_checked": verifying_key is not None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "is_intact": False,
            "reason": f"verification error: {type(exc).__name__}",
            "failed_position": None,
        }


def _render_trace_html(
    *,
    agent_id: str,
    agent_name: str,
    session,
    records: list[dict[str, Any]],
    verification: dict[str, Any],
) -> str:
    """Server-side render the trace as HTML. No JS framework; one self-contained page."""
    intact = verification["is_intact"]
    badge_color = "#3fb950" if intact else "#f85149"
    badge_text = "CHAIN INTACT" if intact else "CHAIN BROKEN"
    badge_detail = ""
    if not intact:
        reason = verification.get("reason") or "unknown"
        pos = verification.get("failed_position")
        badge_detail = f"at position {pos}: {html.escape(reason)}" if pos is not None else html.escape(reason)

    sig_status = ""
    if verification.get("signature_checked"):
        sig_status = "signatures verified"
    elif any(r.get("signature") for r in records):
        sig_status = "signatures present, public key not on file"
    else:
        sig_status = "no signatures (chain-only mode)"

    record_cards = "\n".join(
        _render_record_card(i, r) for i, r in enumerate(records)
    )

    closed_at_line = ""
    if session.closed_at:
        closed_at_line = (
            f'<div class="meta-row"><span class="k">Closed at</span>'
            f'<span class="v">{html.escape(session.closed_at)}</span></div>'
        )
        if session.session_hash:
            closed_at_line += (
                f'<div class="meta-row"><span class="k">Session hash</span>'
                f'<span class="v mono">{html.escape(session.session_hash)}</span></div>'
            )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Conduct trace · {html.escape(agent_name)} · Headlights</title>
<style>
:root {{
  --bg: #0e1116; --bg-card: #161b22; --bg-row-alt: #1a1f27;
  --fg: #e6edf3; --fg-dim: #9aa6b4; --fg-faint: #6e7a8a;
  --accent: #58a6ff; --good: #3fb950; --warn: #d29922; --bad: #f85149;
  --border: #30363d;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--fg); font-family: var(--sans); line-height: 1.5; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 40px 24px 80px; }}
header {{ border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 28px; }}
.eyebrow {{ font-family: var(--mono); font-size: 12px; letter-spacing: 0.1em; color: var(--fg-faint); text-transform: uppercase; margin-bottom: 8px; }}
h1 {{ font-size: 28px; margin: 0 0 6px; font-weight: 600; letter-spacing: -0.01em; }}
.subtitle {{ color: var(--fg-dim); font-size: 14px; }}
.subtitle .mono {{ font-family: var(--mono); font-size: 13px; }}

.status {{ display: inline-flex; align-items: center; padding: 8px 14px; border-radius: 6px; font-family: var(--mono); font-size: 13px; font-weight: 600; letter-spacing: 0.05em; background: {badge_color}22; color: {badge_color}; border: 1px solid {badge_color}55; margin-top: 16px; }}
.status .dot {{ width: 8px; height: 8px; border-radius: 50%; background: {badge_color}; margin-right: 10px; box-shadow: 0 0 8px {badge_color}88; }}
.status-detail {{ display: block; color: var(--fg-dim); font-family: var(--mono); font-size: 12px; margin-top: 6px; }}

.meta-grid {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 18px 22px; margin: 24px 0; font-size: 14px; }}
.meta-row {{ display: flex; padding: 5px 0; border-bottom: 1px dashed var(--border); }}
.meta-row:last-child {{ border-bottom: none; }}
.meta-row .k {{ width: 160px; color: var(--fg-faint); font-family: var(--mono); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
.meta-row .v {{ flex: 1; color: var(--fg); }}
.meta-row .v.mono {{ font-family: var(--mono); font-size: 13px; word-break: break-all; }}

.actions {{ display: flex; gap: 12px; margin: 24px 0 8px; }}
.btn {{ display: inline-flex; align-items: center; padding: 10px 18px; background: var(--bg-card); color: var(--fg); border: 1px solid var(--border); border-radius: 6px; font-family: var(--mono); font-size: 13px; cursor: pointer; }}
.btn:hover {{ border-color: var(--accent); color: var(--accent); text-decoration: none; }}
.btn.primary {{ background: var(--accent); color: #0d1117; border-color: var(--accent); }}
.btn.primary:hover {{ background: #79b8ff; color: #0d1117; }}

h2 {{ font-size: 18px; margin: 36px 0 16px; }}
.record {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; margin: 10px 0; }}
.record.lifecycle {{ border-left: 3px solid var(--accent); }}
.record-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }}
.record-head .pos {{ font-family: var(--mono); font-size: 12px; color: var(--fg-faint); }}
.record-head .ts {{ font-family: var(--mono); font-size: 12px; color: var(--fg-dim); }}
.record-head .type {{ font-family: var(--mono); font-size: 13px; color: var(--fg); font-weight: 600; }}
.record-head .outcome {{ display: inline-block; font-family: var(--mono); font-size: 11px; padding: 2px 8px; border-radius: 3px; margin-left: 8px; text-transform: uppercase; letter-spacing: 0.04em; }}
.outcome.success {{ background: rgba(63, 185, 80, 0.15); color: var(--good); }}
.outcome.failure {{ background: rgba(248, 81, 73, 0.15); color: var(--bad); }}
.outcome.partial {{ background: rgba(210, 153, 34, 0.15); color: var(--warn); }}
.record-detail {{ font-family: var(--mono); font-size: 12px; color: var(--fg-dim); background: var(--bg); padding: 10px 12px; border-radius: 4px; white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow-y: auto; margin-top: 8px; }}
.hash-line {{ font-family: var(--mono); font-size: 11px; color: var(--fg-faint); margin-top: 8px; }}
.hash-line span {{ margin-right: 16px; }}
.hash-line .sig {{ color: var(--good); }}
.hash-line .nosig {{ color: var(--fg-faint); }}

footer {{ border-top: 1px solid var(--border); margin-top: 48px; padding-top: 20px; color: var(--fg-faint); font-family: var(--mono); font-size: 12px; }}
footer p {{ margin: 4px 0; }}

@media (max-width: 640px) {{
  .wrap {{ padding: 24px 14px 48px; }}
  h1 {{ font-size: 22px; }}
  .meta-row {{ flex-direction: column; }}
  .meta-row .k {{ width: auto; margin-bottom: 2px; }}
  .actions {{ flex-direction: column; }}
}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">Headlights · Public conduct trace</div>
  <h1>{html.escape(agent_name)}</h1>
  <div class="subtitle">Session <span class="mono">{html.escape(session.session_id)}</span></div>
  <div class="status"><span class="dot"></span>{badge_text}</div>
  {f'<span class="status-detail">{badge_detail}</span>' if badge_detail else ''}
</header>

<section>
  <div class="meta-grid">
    <div class="meta-row"><span class="k">Agent ID</span><span class="v mono">{html.escape(agent_id)}</span></div>
    <div class="meta-row"><span class="k">Started at</span><span class="v">{html.escape(session.started_at)}</span></div>
    {closed_at_line}
    <div class="meta-row"><span class="k">Records</span><span class="v mono">{len(records)}</span></div>
    <div class="meta-row"><span class="k">Signatures</span><span class="v">{sig_status}</span></div>
  </div>

  <div class="actions">
    <a class="btn primary" href="/v1/sessions/{html.escape(session.session_id)}/trace.json" download>Download canonical JSON</a>
    <a class="btn" href="https://github.com/saffronandindia/headlights-oss#verify" target="_blank" rel="noopener">Verify this yourself <span style="opacity:.6;margin-left:4px;">↗</span></a>
  </div>
  <p class="subtitle" style="margin-top:14px;font-size:13px;">
    Don't trust this page. Download the canonical JSON and run
    <code style="font-family:var(--mono);background:var(--bg-card);padding:1px 6px;border-radius:3px;">pip install headlights-verify &amp;&amp; headlights-verify trace.json</code>.
    If we tamper with this record before you read it, the verifier will catch it.
  </p>
</section>

<section>
  <h2>Records ({len(records)})</h2>
  {record_cards}
</section>

<footer>
  <p>Generated by Headlights — <a href="https://github.com/saffronandindia/headlights-oss">github.com/saffronandindia/headlights-oss</a></p>
  <p>Implementing <a href="https://datatracker.ietf.org/doc/html/draft-sharif-agent-audit-trail-00">IETF AAT draft</a> · SHA-256 hash chain · ECDSA P-256 signatures · Apache 2.0</p>
</footer>

</div>
</body>
</html>"""


def _render_record_card(position: int, record: dict[str, Any]) -> str:
    action_type = record.get("action_type", "?")
    outcome = record.get("outcome", "?")
    ts = record.get("timestamp", "")
    detail = record.get("action_detail", {})

    is_lifecycle = action_type == "lifecycle"
    record_class = "record lifecycle" if is_lifecycle else "record"

    # Compute the record hash for display
    try:
        record_hash = record_hash_for_chain(record)
        record_hash_short = record_hash[:16]
    except Exception:  # noqa: BLE001
        record_hash_short = "—"

    prev_hash = record.get("prev_hash") or ""
    prev_hash_display = prev_hash[:16] if prev_hash else "(genesis)"

    has_sig = bool(record.get("signature"))
    sig_html = (
        '<span class="sig">✓ signed</span>'
        if has_sig
        else '<span class="nosig">— unsigned</span>'
    )

    detail_json = html.escape(json.dumps(detail, indent=2, sort_keys=True))
    outcome_class = outcome if outcome in ("success", "failure", "partial") else "success"

    return f"""
  <div class="{record_class}">
    <div class="record-head">
      <span class="pos">#{position}</span>
      <span class="type">{html.escape(action_type)}<span class="outcome {outcome_class}">{html.escape(outcome)}</span></span>
      <span class="ts">{html.escape(ts)}</span>
    </div>
    <div class="record-detail">{detail_json}</div>
    <div class="hash-line">
      <span>hash <code>{html.escape(record_hash_short)}…</code></span>
      <span>prev <code>{html.escape(prev_hash_display)}{'…' if prev_hash else ''}</code></span>
      <span>{sig_html}</span>
    </div>
  </div>"""
