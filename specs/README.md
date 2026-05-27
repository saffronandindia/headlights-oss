# specs

The protocol specifications and design decisions Headlights is built on.

## What's here

- [`chain.md`](chain.md) — the on-wire record format, JCS canonicalisation, hash chain construction, signature scheme. The protocol document a third-party implementer would need to write a compatible verifier in another language.
- [`decisions.md`](decisions.md) — architecture decision records. The reasoning behind ECDSA P-256 (not Ed25519), session-scoped chains (not lifetime), private-by-default, and other choices that have shaped the codebase.
- [`scorecard-research.md`](scorecard-research.md) — the comparative analysis of existing AI accountability frameworks that the Conduct Scorecard rubric is grounded in.
- [`scorecard-rubric.md`](scorecard-rubric.md) — the AI Conduct Scorecard, the framework this project uses to measure whether an AI deployment meets the bar.

## Why a spec at all

Headlights aligns with [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/) at the IETF. The point is that the wire format is not a Headlights-proprietary thing — any team can implement it without depending on this codebase. The spec docs here are the bridge between the IETF draft and this implementation.
