# Headlights

**A tamper-evident record of what your AI agent actually did.**

When an AI agent gets something wrong (and one of them will), the institution that deployed it almost never has the evidence to reconstruct what the agent saw, what it inferred, what it did, and who authorised it. Aircraft have flight recorders. Production AI agents do not. Headlights is built to fill that gap.

It is aimed at the teams who have to answer for an agent in production: the developers who build it, and the platform, risk, and compliance owners who stand behind what it does.

Install the SDK in the workflow your agent runs in, record every decision the agent takes, and produce a signed, append-only chain that a regulator, a court, or a customer's lawyer can verify months or years later. Open-source, no vendor lock-in, no proprietary auditor in the loop.

Built on the [Agent Audit Trail draft](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/), an individual IETF submission not yet Working-Group adopted. Apache 2.0 licensed. Companion field notes on real AI agent failures live at [useheadlights.com](https://useheadlights.com).

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
| [`marketing/`](marketing/) | Dogfooded agents (discovery, drafter, upload). Themselves recorded into Headlights chains when they run. |
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

Each call your agent makes becomes a *conduct record*: a signed, timestamped entry capturing the model version, the inputs, the outputs, and the outcome. Those records link into one tamper-evident chain per session, which is what the guards below write through and the verifier checks.

## Governance guards

On top of the raw record API, the SDK ships a thin layer of named **governance guards**: pre- and post-execution checks that each record their decision as a valid AAT record. They turn the failure patterns catalogued in the [Headlights incident library](https://useheadlights.com/library) into code you can run. Eight modules, in two layers.

**Record layer** (written after the action): `ConductRecord`, `MetricRecord`.

**Gate layer** (enforced before the action, in order): `AuthorityGate`, `ConstraintGate`, `PersonaGuard`, `CitationVerifier`, `VerificationGate`, `EgressGate`.

Shipping now are the two gates with no existing equivalent in the toolkit: **AuthorityGate** (is the instruction's source authorised to bind the agent?) and **EgressGate** (is sensitive data leaving the trust boundary?). The remaining modules follow the same thin pattern: no new crypto, no new record format, just named checks that delegate to the chain.

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

Full detail in [the guards README](sdk-python/headlights_sdk/guards/README.md), and the live module rundown is at [useheadlights.com/code](https://useheadlights.com/code).

## Status

Pre-launch alpha (v0.1.0a1). The chain primitive, verifier CLI, SDK (including the new governance-guards layer), reference server, scorecard rubric and dogfooded marketing pipeline are all functional and covered by the test suite. Hosted platform, web dashboard polish, and PyPI publication are still ahead.

Aligned with the [Agent Audit Trail draft](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/), an individual IETF submission not yet Working-Group adopted. See [`specs/chain.md`](specs/chain.md) and [`specs/decisions.md`](specs/decisions.md) for the protocol details, and [`specs/scorecard-rubric.md`](specs/scorecard-rubric.md) for the conduct scorecard.

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

Apache 2.0, Copyright Stellae Consulting Pty Ltd. See [LICENSE](LICENSE).
