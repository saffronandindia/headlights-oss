# headlights-sdk

Six months from now, the regulator will ask what your agent did on a specific date. The institutions that can answer with evidence will outcompete the ones that can't. This SDK is the one-decorator way to be in the first group. Wrap any function your agent calls, and every invocation is recorded into a tamper-evident chain you can prove was untouched.

Local-only at v1 — records live in memory and you export them to verify or persist. v2 will ship a hosted client that streams to `api.useheadlights.com`.

## Install

```bash
pip install headlights-sdk
```

(Until the first PyPI release, install from source: `pip install -e ./chain ./sdk-python`.)

## Quick start

```python
from headlights_sdk import Client
from headlights_chain import generate_keypair

signing_key, verifying_key = generate_keypair()

client = Client(
    agent_id="urn:headlights:agent:loan-analyser",
    agent_version="3.1.0",
    signing_key=signing_key,
)

@client.record
def lookup_credit_score(applicant_id: str) -> int:
    # ... real logic ...
    return 750

score = lookup_credit_score("APP-001")   # records tool_call + tool_response
score = lookup_credit_score("APP-002")   # appends two more records

client.close()                            # writes session_end

# Export and verify:
records = client.export()
# Pass to `headlights-verify` or use it programmatically:
from headlights_chain import Chain
Chain.from_records(records).verify(verifying_key=verifying_key).is_intact  # True
```

## What gets recorded

For each decorated function call, three records can hit the chain:

- A `tool_call` record (always) — hashes the input arguments into `parameters_hash`.
- A `tool_response` record (on success) — hashes the return value into `response_hash`, captures latency, points at the matching call via `parent_call_id`.
- An `error` record (on exception) — captures the exception type, message, and a hashed stack trace. The exception is then re-raised; the SDK never silently swallows errors.

## Sessions

By default the first decorated call auto-opens a session. For finer control, use the context manager:

```python
with client.session(genesis_detail={"config_hash": "sha256:abc..."}):
    lookup_credit_score("APP-001")
    lookup_credit_score("APP-002")
# session is closed automatically
```

Set `auto_session=False` on the Client constructor to require explicit sessions.

## Governance guards

The `headlights_sdk.guards` sub-package adds named, thin pre/post conditions on
top of the client. Each applies one governance check and records the decision as
a valid AAT record on the chain — no new crypto, no new record format.

```python
from headlights_sdk import Client
from headlights_sdk.guards import AuthorityGate, EgressGate

client = Client(agent_id="urn:org:agent", agent_version="1.0.0")

# Deny instructions from sources not authorised to bind the agent.
AuthorityGate(client, authorised_sources={"urn:org:ops-console"}).enforce(
    source="urn:org:ops-console", instruction="run payroll"
)

# Block sensitive data leaving the trust boundary.
EgressGate(
    client,
    trusted_destinations={"https://internal.corp"},
    sensitive_patterns={"aws_key": r"AKIA[0-9A-Z]{16}"},
).enforce(content=reply, destination="https://partner.example")
```

`AuthorityGate` and `EgressGate` ship today; `ConstraintGate`, `PersonaGuard`,
`CitationVerifier`, `VerificationGate`, and the record helpers follow. See
[`headlights_sdk/guards/README.md`](headlights_sdk/guards/README.md).

## License

Apache 2.0.
