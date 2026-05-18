"""Headlights chain end-to-end demo — the 60-second pitch from the handover §11,
but written against the chain primitive directly (no SDK or storage layer yet).

Run:
    cd headlights-oss
    PYTHONPATH=chain python3 examples/loan_analyser_demo.py

What it does:
    1.  Genesis a new session for a fictional `loan-analyser` agent.
    2.  Sign every record with a freshly-minted ECDSA P-256 key.
    3.  Append three actions: a credit-score lookup, a decision, an escalation.
    4.  Close the session, emitting a session_hash.
    5.  Verify the intact chain — prints GREEN.
    6.  Tamper with one record's action_detail.
    7.  Re-verify — prints RED and reports the first failing position.

This is the script that will become the public demo, just dressed up with
prettier console output and an SDK facade once the SDK lands.
"""

from __future__ import annotations

import copy
import sys

from headlights_chain import (
    Chain,
    Outcome,
    TrustLevel,
    generate_keypair,
)
from headlights_chain.enums import ActionType


def main() -> int:
    signing_key, verifying_key = generate_keypair()

    print("== Headlights chain demo ==")
    print(f"  Verifying key (PEM, first line): {verifying_key.to_pem().splitlines()[0].decode()}")

    chain = Chain.genesis(
        agent_id="urn:headlights:agent:loan-analyser",
        agent_version="3.1.0",
        signing_key=signing_key,
        trust_level=TrustLevel.L2,
        genesis_detail={
            "config_hash": "sha256:demo-config-hash",
            "enabled_tools": ["credit_score_lookup", "policy_engine"],
            "operating_parameters": {"max_loan_value": 1_500_000, "currency": "AUD"},
        },
    )
    print(f"  Genesis written: session_id={chain.records()[0].session_id}")

    chain.append(
        action_type=ActionType.TOOL_CALL,
        action_detail={
            "tool_name": "credit_score_lookup",
            "parameters_hash": "sha256:applicant-pii-hash-1",
        },
        outcome=Outcome.SUCCESS,
        trust_level=TrustLevel.L2,
    )

    chain.append(
        action_type=ActionType.DECISION,
        action_detail={
            "decision_type": "loan_approval_recommendation",
            "reasoning_hash": "sha256:reasoning-blob-1",
            "confidence": 0.87,
            "alternatives_considered": ["approve_with_higher_rate", "request_more_collateral"],
        },
        outcome=Outcome.SUCCESS,
        trust_level=TrustLevel.L2,
        risk_score=0.18,
        jurisdiction="AU",
    )

    chain.append(
        action_type=ActionType.ESCALATION,
        action_detail={
            "escalation_reason": "loan_value_exceeds_autonomous_limit",
            "escalation_target": "urn:headlights:human:senior-credit-officer",
            "urgency": "medium",
        },
        outcome=Outcome.ESCALATED,
        trust_level=TrustLevel.L2,
    )

    close_pos, _ = chain.close()
    print(f"  Session closed at position {close_pos}")
    print(f"  Total records (incl. genesis & close): {len(chain)}")
    print(f"  session_hash: {chain.records()[-1].action_detail['session_hash']}")

    # ── Verify intact chain ─────────────────────────────────────────────
    intact = chain.verify(verifying_key=verifying_key)
    if intact.is_intact:
        print("\n  GREEN: chain intact, all signatures verify.")
    else:
        print(f"\n  Unexpected failure: {intact}")
        return 1

    # ── Tamper and re-verify ────────────────────────────────────────────
    exported = chain.export_records()
    print("\n  Tampering with position 2 (the decision record's confidence)...")
    forged = copy.deepcopy(exported)
    forged[2]["action_detail"]["confidence"] = 0.99  # was 0.87
    forged_chain = Chain.from_records(forged)

    broken = forged_chain.verify(verifying_key=verifying_key)
    if broken.is_intact:
        print("  Unexpected: tampering went undetected.")
        return 1

    print(f"  RED: chain broken at position {broken.failed_position}")
    print(f"  Reason: {broken.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
