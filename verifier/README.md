# headlights-verify

A tamper-evidence claim that only the vendor can verify is not a tamper-evidence claim. This CLI is the verification path turned into something anyone — an auditor, a regulator, the customer's lawyer, a journalist — can install on a laptop and run themselves. No phone-home. No vendor account. No proprietary tooling. Take a chain export, run `headlights-verify`, see for yourself.

Takes a chain export (JSON array or NDJSON), re-runs the integrity checks defined by [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/), and prints `✓ chain intact` or `✗ chain BROKEN` along with the first failing position when tampering is detected. Depends only on `headlights-chain`.

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
