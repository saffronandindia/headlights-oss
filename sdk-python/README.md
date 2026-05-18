# headlights-sdk

Drop a decorator on your agent functions. Every call lands in a tamper-evident, AAT-aligned conduct chain you can later prove was untouched.

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

## License

Apache 2.0.
