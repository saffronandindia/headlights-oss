"""Headlights governance guards — named, thin pre/post conditions.

Each guard wraps a :class:`headlights_sdk.client.Client` and records every
governance decision as a valid AAT record (draft-sharif-agent-audit-trail-00).
The guard names are the Headlights taxonomy; the record format is the spec's.
No new crypto, no new record format.

Layer 2 gates implemented so far::

    from headlights_sdk import Client
    from headlights_sdk.guards import AuthorityGate, EgressGate

    client = Client(agent_id="urn:org:agent", agent_version="1.0.0")

    authority = AuthorityGate(client, authorised_sources={"urn:org:ops-console"})
    authority.enforce(source="urn:org:ops-console", instruction="run payroll")

    egress = EgressGate(
        client,
        trusted_destinations={"https://internal.corp"},
        sensitive_patterns={"aws_key": r"AKIA[0-9A-Z]{16}"},
    )
    egress.enforce(content=reply, destination="https://partner.example")
"""

from headlights_sdk.guards.authority import AuthorityGate
from headlights_sdk.guards.base import Guard, GuardDenied, GuardResult
from headlights_sdk.guards.egress import EgressGate

__all__ = [
    "Guard",
    "GuardResult",
    "GuardDenied",
    "AuthorityGate",
    "EgressGate",
]
