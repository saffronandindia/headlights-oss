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

All eight modules, in two layers.

**Record layer** (write evidence after the action):

| Module | What it records |
| :----- | :-------------- |
| `ConductRecord` | One full conduct record per action: model id, hashed system prompt, retrieved sources, tool calls, hashed output. |
| `MetricRecord` | A signed aggregate metric bound to the chain root hash, so the number can be recomputed from the verified records and proven. |

**Gate layer** (enforce before the action, in pipeline order):

| Gate | Question it answers |
| :--- | :------------------ |
| `AuthorityGate` | Who issued this instruction, and are they authorised to bind the agent? Runs first; source and authority only, not policy. |
| `ConstraintGate` | Does this action comply with the declared standing rules? |
| `PersonaGuard` | Does this reply match the agent's defined identity and scope? |
| `CitationVerifier` | Is every citation real, checked against a trusted source? |
| `VerificationGate` | Is this claim true, routed to a trusted source rather than back to the model? |
| `EgressGate` | Does this output carry sensitive data bound for outside the trust boundary? |

Each gate denies with a `decision` / `denied` AAT record and raises from
`enforce()`. Sensitive inputs (replies, claims, prompts, outputs, and matched
sensitive content) are hashed, never stored raw.

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
pytest tests/test_guards.py tests/test_guards_modules.py -q
```

Twenty-one tests across `test_guards.py` and `test_guards_modules.py` cover the
deny and allow paths for every gate, the `enforce()` raise on denial, the two
record helpers, the guarantee that raw content is never stored, and signed-chain
verification. The constraint each one asserts: a guard's failure path must still
write a valid AAT record, a registered `action_type` and `outcome`, on a chain
that verifies intact.
