"""Headlights governance guards — named, thin pre/post conditions.

Each guard wraps a :class:`headlights_sdk.client.Client` and records every
governance decision as a valid AAT record (draft-sharif-agent-audit-trail-00).
The guard names are the Headlights taxonomy; the record format is the spec's.
No new crypto, no new record format.

Eight modules in two layers.

Record layer (write evidence after the action)::

    from headlights_sdk.guards import ConductRecord, MetricRecord

Gate layer (enforce before the action, in order)::

    from headlights_sdk.guards import (
        AuthorityGate, ConstraintGate, PersonaGuard,
        CitationVerifier, VerificationGate, EgressGate,
    )
"""

from headlights_sdk.guards.authority import AuthorityGate
from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult
from headlights_sdk.guards.citation import CitationVerifier
from headlights_sdk.guards.conduct import ConductRecord
from headlights_sdk.guards.constraint import ConstraintGate
from headlights_sdk.guards.egress import EgressGate
from headlights_sdk.guards.metric import MetricRecord
from headlights_sdk.guards.persona import PersonaGuard
from headlights_sdk.guards.verification import VerificationGate

__all__ = [
    # Base
    "Guard",
    "GuardResult",
    "GuardDenied",
    # Record layer
    "ConductRecord",
    "MetricRecord",
    # Gate layer (pipeline order)
    "AuthorityGate",
    "ConstraintGate",
    "PersonaGuard",
    "CitationVerifier",
    "VerificationGate",
    "EgressGate",
]
