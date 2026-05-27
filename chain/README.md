# headlights-chain

When the question is "what did the AI agent actually do?", the answer needs to survive an adversary with admin access to the database the agent wrote to. This package is the cryptographic primitive that makes the answer survive: a SHA-256 hash chain over JCS-canonicalised records, with optional ECDSA P-256 signatures. It knows nothing about databases, tenants, HTTP, or agents. Everything else in this repo — the SDK, the verifier, the server — is built on top of it.

Pure Python, persistence-agnostic, AAT-aligned.

Implements the record format and chain mechanics of [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/):

- SHA-256 hash chain over JCS-canonicalised (RFC 8785) record bodies
- ECDSA P-256 signatures (optional), IEEE P1363 r||s encoding per AAT §4.2
- Genesis and session-close record helpers
- `verify()` returns the position of the first tampered record, or `None` if intact

This package is the cryptographic primitive. It knows nothing about databases, tenants, agents, billing, or HTTP. The `headlights-sdk`, `headlights-verify`, and hosted platform are built on top of it.

## Install (development)

```bash
cd chain
pip install -e ".[dev]"
pytest
```

## Quick start

```python
from headlights_chain import Chain, Outcome, TrustLevel, generate_keypair

signing_key, verifying_key = generate_keypair()

chain = Chain.genesis(
    agent_id="urn:headlights:agent:loan-analyser-v3",
    agent_version="3.1.0",
    signing_key=signing_key,
    genesis_detail={"config_hash": "sha256:abc...", "enabled_tools": ["credit_score_lookup"]},
)

position, record_hash = chain.append(
    action_type="tool_call",
    action_detail={"tool_name": "credit_score_lookup", "parameters_hash": "sha256:..."},
    outcome=Outcome.SUCCESS,
    trust_level=TrustLevel.L2,
)

chain.close()  # writes the session_end lifecycle record with session_hash

assert chain.verify(verifying_key=verifying_key).is_intact
```

## Files

- `headlights_chain/enums.py` — AAT-defined enums (action_type, outcome, trust_level, lifecycle event)
- `headlights_chain/canonical.py` — JCS canonicalisation + SHA-256 hashing
- `headlights_chain/signatures.py` — ECDSA P-256 sign/verify with P1363 encoding
- `headlights_chain/records.py` — Pydantic record model with AAT field validation
- `headlights_chain/chain.py` — `Chain` class: genesis, append, close, verify, export, import

## Status

Pre-launch (v0.1.0-alpha). The on-wire record format is stable per AAT-00 alignment; the Python API surface may evolve.

## License

Apache 2.0.
