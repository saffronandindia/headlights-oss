# Headlights governance guards

When an AI agent acts, the damage is usually done before anyone checks whether it
should have. These guards are that check: named, thin pre/post conditions that sit
on top of the Headlights SDK. Each guard wraps a `headlights_sdk.Client`, applies
one governance check, and records the decision as a valid AAT record on the
client's chain.

Part of [Headlights](https://useheadlights.com). The failure patterns these
guards address are documented, with sources, in the
[incident library](https://useheadlights.com/library).

The guard **names** are the Headlights taxonomy. The record **format** is the
spec's: it follows [draft-sharif-agent-audit-trail-00](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/).
Guards add no new crypto and no new record format; they delegate to
`client.record_action` / `Chain.append`.

> **Spec status:** the Agent Audit Trail draft is an individual IETF submission by
> Raza Sharif (29 March 2026), not yet Working-Group adopted. Treat the record
> format as stable in practice, but not a ratified standard.

## What's here

Two of the eight planned modules: the two Layer-2 gates that have no existing
equivalent in the toolkit.

| Guard | Question it answers | Records |
| :---- | :------------------ | :------ |
| `AuthorityGate` | Who issued this instruction, and are they authorised to bind the agent? Runs first; source and authority only, not policy. | `decision` / `denied` on an unauthorised source |
| `EgressGate` | Does this output carry sensitive data, and is the destination inside the trust boundary? Runs where data would leave; classification and destination only, not content moderation. | `decision` / `denied` when sensitive data is bound for an untrusted destination |

Still to come (same pattern): `ConstraintGate`, `PersonaGuard`,
`CitationVerifier`, `VerificationGate`, and the `ConductRecord` / `MetricRecord`
record helpers.

## Usage

```python
from headlights_sdk import Client
from headlights_sdk.guards import AuthorityGate, EgressGate, GuardDenied

client = Client(agent_id="urn:org:agent", agent_version="1.0.0")

# AuthorityGate: verify the instruction source before acting.
authority = AuthorityGate(client, authorised_sources={"urn:org:ops-console"})
result = authority.check(source="urn:unknown:caller", instruction="delete all user records")
assert result.allowed is False            # recorded as decision/denied

# Or block hard:
try:
    authority.enforce(source="urn:unknown:caller")
except GuardDenied as denied:
    ...  # denied.result is the GuardResult

# EgressGate: stop sensitive data leaving the trust boundary.
egress = EgressGate(
    client,
    trusted_destinations={"https://internal.corp"},
    sensitive_patterns={
        "aws_access_key": r"AKIA[0-9A-Z]{16}",
        "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    },
)
egress.enforce(content=model_reply, destination="https://partner.example")
```

Every check returns a `GuardResult` (`allowed`, `reason`, `record_position`,
`detail`) and writes one AAT record. `EgressGate` records a SHA-256 hash of the
content and the matched categories, never the raw sensitive content itself.

A single `Client` holds one session-scoped chain. Attach as many guards as you
like to the same client and they all record to that one chain. `Client` is not
thread-safe, so instantiate one client (with its guards) per agent session rather
than sharing a client across threads.

## Design rule

A guard earns its place only when (a) existing modules cannot express the
failure without distortion, and (b) the pattern recurs across multiple
independent incidents. `AuthorityGate` fills the AAT's deferred
mission-to-authorisation step (seen in: DPD prompt injection, Chevrolet "$1
Tahoe"). `EgressGate` covers trust-boundary enforcement the drafts leave empty
(seen in: Samsung source-code leak, McHire data exposure).

## Tests

```sh
cd sdk-python
pip install -e ".[dev]" -e ../chain
pytest tests/test_guards.py -q
```

Seven tests cover the deny and allow paths for both guards, the `enforce()` raise
on denial, the guarantee that `EgressGate` never stores raw content, and
signed-chain verification. The constraint each one asserts: a guard's failure path
must still write a valid AAT record, a registered `action_type` and `outcome`, on a
chain that verifies intact.
