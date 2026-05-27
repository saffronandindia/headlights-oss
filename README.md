# Headlights

**A tamper-evident record of what your AI agent actually did.**

When an AI agent gets something wrong — and one of them will — the institution that deployed it almost never has the evidence to reconstruct what the agent saw, what it inferred, what it did, and who authorised it. Aircraft have flight recorders. Production AI agents do not. Headlights is the missing piece.

Install the SDK in the workflow your agent runs in, record every decision the agent takes, and produce a signed, append-only chain that a regulator, a court, or a customer's lawyer can verify months or years later. Open-source, no vendor lock-in, no proprietary auditor in the loop.

Built on the [IETF Agent Audit Trail draft](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/). Apache 2.0 licensed. Companion field notes on real AI agent failures live at [useheadlights.com](https://useheadlights.com).

## Packages

| Path | What it is |
| --- | --- |
| [`chain/`](chain/) | The hash-chain primitive. ECDSA P-256 signatures, append-only, tamper-evident. |
| [`sdk-python/`](sdk-python/) | Python SDK for emitting conduct records into a chain from inside an agent. |
| [`verifier/`](verifier/) | Public CLI for verifying any chain export. Stateless. No phone-home. |
| [`server/`](server/) | Reference FastAPI backend for hosting chains, with a trace-viewer endpoint. |
| [`dashboard-reference/`](dashboard-reference/) | Minimal Next.js dashboard that reads from the reference server. |
| [`scorecard/`](scorecard/) | Static rubric for the AI Conduct Scorecard. |
| [`specs/`](specs/) | Protocol specifications. Chain format, decisions, scorecard research and rubric. |
| [`marketing/`](marketing/) | Self-dogfooding agents (discovery, drafter, upload). Themselves recorded into Headlights chains when they run. |
| [`examples/`](examples/) | End-to-end demos. Start here. |

## Quick start

```bash
# From a checkout of this repo:
pip install -e ./chain ./sdk-python ./verifier ./server

# Generate a signed conduct chain via the SDK:
python examples/loan_analyser_demo.py

# Verify any chain export:
headlights-verify path/to/chain.json
```

Five minutes to your first proof.

## Status

Pre-launch alpha (v0.1.0a1). The chain primitive, verifier CLI, SDK, reference server, scorecard rubric and self-dogfooding marketing pipeline are all functional and tested (**226 tests passing** as of the most recent commit). Hosted platform, web dashboard polish, and PyPI publication are still ahead.

Aligned with [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/). See [`specs/chain.md`](specs/chain.md) and [`specs/decisions.md`](specs/decisions.md) for the protocol details, and [`specs/scorecard-rubric.md`](specs/scorecard-rubric.md) for the conduct scorecard.

## Running the tests

```bash
# Install everything as editable so packages can see each other
pip install -e ./chain ./sdk-python ./verifier ./server

# Run the full suite from the repo root
PYTHONPATH=chain:sdk-python:verifier:server:. python -m pytest -q
```

## Security

If you find a vulnerability, please follow the disclosure process in [SECURITY.md](SECURITY.md). Do not file public GitHub issues for security bugs.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache 2.0. See [LICENSE](LICENSE).

Copyright Stellae Consulting Pty Ltd.
