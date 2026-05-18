# headlights-verify

Public verifier CLI for Headlights AI agent conduct chains.

Takes a chain export (JSON array or NDJSON), re-runs the integrity checks defined by [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/), and prints `✓ chain intact` or `✗ chain BROKEN` along with the first failing position when tampering is detected.

This package depends only on `headlights-chain`. It is intentionally tiny so anyone — auditors, regulators, customers, journalists — can install it on a fresh laptop and re-verify a conduct record themselves.

## Install

```bash
pip install headlights-verify
```

(Until the first PyPI release, install from source: `pip install -e ./chain ./verifier`.)

## Usage

```bash
headlights-verify path/to/chain.json
headlights-verify path/to/chain.ndjson --public-key agent.pem
python -m headlights_verify path/to/chain.json   # equivalent
```

Exit codes:

- `0` chain is intact
- `1` chain is broken (tampered or signature failure) — the failing position and reason are printed to stdout
- `2` input error (file not found, bad JSON, missing key)

## License

Apache 2.0.
