# Headlights governance guards

Named, thin pre/post conditions that sit on top of the Headlights SDK. Each
guard wraps a `headlights_sdk.Client`, applies one governance check, and records
the decision as a valid AAT record on the client's chain.

The guard **names** are the Headlights taxonomy. The record **format** is the
spec's — [draft-sharif-agent-audit-trail-00](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/),
an individual IETF submission by Raza Sharif (29 March 2026), not yet
Working-Group adopted. Guards add no new crypto and no new record format; they
delegate to `client.record_action` / `Chain.append`.

## What's here

Two of the eight planned modules — the two Layer-2 gates that have no existing
equivalent in the toolkit:

| Guard | Question it answers | Records |
| :---- | :------------------ | :------ |
| `AuthorityGate` | Who issued this instruction, and are they authorised to bind the agent? Runs first; source and authority only, not policy. | `decision` / `denied` on an unauthorised source |
| `EgressGate` | Does this output carry sensitive data, and is the destination inside the trust boundary? Runs where data would leave; classification and destination only, not content moderation. | `decision` / `denied` when sensitive data is bound for an untrusted destination |

Still to come (same thin pattern): `ConstraintGate`, `PersonaGuard`,
`CitationVerifier`, `VerificationGate`, and the `ConductRecord` / `MetricRecord`
record helpers.

## Usage

```python
from headlights_sdk import Client
from headlights_sdk.guards import AuthorityGate, EgressGate, GuardDenied

client = Client(agent_id="urn:org:agent", agent_version="1.0.0")

# AuthorityGate — verify the instruction source before acting.
authority = AuthorityGate(client, authorised_sources={"urn:org:ops-console"})
result = authority.check(source="urn:unknown:caller", instruction="wipe the db")
assert result.allowed is False            # recorded as decision/denied

# Or block hard:
try:
    authority.enforce(source="urn:unknown:caller")
except GuardDenied as denied:
    ...  # denied.result is the GuardResult

# EgressGate — stop sensitive data leaving the trust boundary.
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
content and the matched categories — never the raw sensitive content itself.

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

The failure path of each guard must write a valid AAT record — a registered
`action_type` and `outcome`, on a chain that still verifies intact.
