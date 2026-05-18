"""Headlights chain — tamper-evident hash chain for AI agent conduct records.

Implements draft-sharif-agent-audit-trail-00 record format and chain mechanics.
"""

from headlights_chain.chain import Chain, ChainState, VerificationResult
from headlights_chain.enums import (
    ActionType,
    LifecycleEvent,
    Outcome,
    TrustLevel,
)
from headlights_chain.records import Record
from headlights_chain.signatures import (
    SigningKey,
    VerifyingKey,
    generate_keypair,
)

__version__ = "0.1.0a1"
__all__ = [
    "Chain",
    "ChainState",
    "VerificationResult",
    "Record",
    "ActionType",
    "Outcome",
    "TrustLevel",
    "LifecycleEvent",
    "SigningKey",
    "VerifyingKey",
    "generate_keypair",
]
