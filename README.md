# Headlights

**GitHub for AI conduct records.**

Open-source registry for AI agent conduct records. Install the SDK, record what your agents do, prove what happened. Free hosted version, self-host the whole stack, or use the managed platform.

Built on the IETF Agent Audit Trail standard. Apache 2.0 licensed.

## Packages

- `chain/` — Hash chain implementation
- `sdk-python/` — Python SDK (`pip install headlights-sdk`)
- `verifier/` — Public verifier CLI (`pip install headlights-verify`)
- `dashboard-reference/` — Minimal reference dashboard (Next.js)
- `specs/` — Protocol specifications
- `examples/` — End-to-end demos

## Quick start

```bash
# From a checkout of this repo:
pip install -e ./chain ./sdk-python ./verifier

# Generate a signed conduct chain via the SDK:
python examples/loan_analyser_demo.py

# Verify any chain export:
headlights-verify path/to/chain.json
```

Five minutes to your first proof.

## Status

Pre-launch alpha (v0.1.0a1). The chain primitive, verifier CLI, and SDK are functional and tested (**124 tests passing**). Hosted platform, web dashboard, and PyPI publication are still ahead.

Aligned with [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/) — see [`specs/chain.md`](specs/chain.md) and [`specs/decisions.md`](specs/decisions.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).

Copyright Stellae Consulting Pty Ltd.
