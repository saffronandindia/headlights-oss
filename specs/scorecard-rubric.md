# AI Conduct Scorecard — Rubric

Version 1.0 · Published 2026-05-19

This document defines how each AI product is scored on the Headlights AI Conduct Scorecard. Scores are derived from public documentation only — vendor docs, security pages, compliance pages, blog posts, API docs. Where a vendor is silent on a dimension, the dimension scores zero. We do not infer or speculate.

The Scorecard is published openly so vendors can dispute scores by opening an issue in this repository. Every score is footnoted with the source documentation it was drawn from.

## Why these seven dimensions

The dimensions are derived from the IETF Agent Audit Trail draft (`draft-sharif-agent-audit-trail-00`), the EU AI Act Article 12 logging requirements, ISO/IEC 42001:2023, and the SOC 2 Trust Services Criteria. They answer a single question: **"If a regulator, auditor, court, or board asked what your AI agent actually did, could you prove it?"**

The seven dimensions break that question into measurable parts: can records be tampered with (A, B), are they kept long enough to matter (C), do they capture enough to reconstruct what happened (D), can integrity be confirmed without trusting the vendor (E, F), and does any open standard apply (G)?

## Scoring scale

Each dimension scores 0–3. Total possible: 21.

- **0** — No public documentation, or explicit absence of the property
- **1** — Weak coverage (claims without mechanism, partial implementation, short retention)
- **2** — Solid coverage (documented mechanism, reasonable defaults, customer access)
- **3** — Strong coverage (verifiable mechanism, long retention, independently auditable, open standard alignment)

## The seven dimensions

### A. Tamper evidence

Is the log cryptographically resistant to modification, or does the vendor merely promise it won't modify it?

| Score | Criterion |
|---|---|
| 0 | No immutability claim, or admins can delete entries |
| 1 | Vendor-policy "immutable" claim with no cryptographic mechanism documented |
| 2 | Documented cryptographic chain — entries link to prior entries via hash |
| 3 | Documented cryptographic chain *and* per-entry signatures, both independently verifiable |

### B. Per-record signatures

Can a specific log entry be proven to have been issued by the vendor (or the agent), as distinct from later inserted?

| Score | Criterion |
|---|---|
| 0 | No per-entry signature scheme |
| 1 | Authentication-layer signatures (e.g., signed JWT for API access) but not per-log-entry |
| 2 | Optional per-entry signatures documented |
| 3 | Mandatory per-entry signatures backed by registered public keys |

### C. Retention

How long are records kept by default? Can customers configure longer retention?

| Score | Criterion |
|---|---|
| 0 | <30 days, or unstated |
| 1 | 30–365 days |
| 2 | 1–5 years, or customer-configurable to that range |
| 3 | 5+ years default, or fully customer-configurable up to 10+ years |

### D. Replayability

Can the AI's actual behaviour — what it was asked, what it produced, what it decided — be reconstructed from the log?

| Score | Criterion |
|---|---|
| 0 | No log access for AI interactions, or prompts and responses explicitly excluded |
| 1 | Metadata only (events, timestamps, file references, but no prompt or response content) |
| 2 | Content captured (prompt + response) |
| 3 | Full decision trace (prompt + response + tool calls + intermediate reasoning + outcomes) |

### E. External anchoring

Are log hashes committed to a medium outside the vendor's control, so even the vendor cannot quietly rewrite history?

| Score | Criterion |
|---|---|
| 0 | None |
| 1 | Vendor-controlled append-only storage (e.g., WORM blob storage in the vendor's own cloud) |
| 2 | Time-stamped to an external trusted third party (e.g., RFC 3161 trusted timestamping) |
| 3 | Anchored to a public immutable medium (public blockchain, public certificate transparency log, or equivalent) |

### F. Independent verifiability

Can a customer (or their auditor) independently confirm log integrity without trusting the vendor's UI?

| Score | Criterion |
|---|---|
| 0 | No customer export |
| 1 | UI download only (CSV / PDF) |
| 2 | API export with documented schema |
| 3 | Standalone verifier tool that customers can run offline to confirm integrity without contacting the vendor |

### G. Standards alignment

Does the product align with any open AI-specific audit standard?

| Score | Criterion |
|---|---|
| 0 | No AI-specific compliance |
| 1 | General compliance only (SOC 2, ISO 27001, etc.) |
| 2 | AI-specific certification (ISO/IEC 42001:2023) or substantive alignment claim |
| 3 | Reference implementation of an open AI audit standard (IETF AAT or equivalent) |

## Scoring conventions

**Vendor-claims-only flag.** If a vendor's claims for a dimension cannot be substantiated from public technical documentation, the dimension is marked **U** (unverified) rather than zeroed. The product's total is then displayed as "Unverified" rather than as a number — we don't want to penalise a vendor who simply lacks public docs, nor reward a vendor whose marketing copy can't be checked.

**Re-scoring cadence.** The Scorecard is re-scored quarterly. Vendors who publish new documentation between quarterly updates can request an early re-score by opening an issue.

**Disputes.** A vendor who disagrees with their score may open an issue. We respond publicly with the specific documentation cited or, where appropriate, raise the score and credit the correction.

## The Headlights self-score

Headlights scores **19/21** on its own rubric. We score ourselves transparently because anything else would invalidate the exercise. The points we do not award ourselves:

- **E. External anchoring — 1/3.** The Anchor interface and Merkle-tree builder ship in the open-source repository, but the production Azure Immutable Blob adapter is not yet deployed. Until the hosted backend writes a daily Merkle root to an external WORM medium, this dimension caps at 1. We expect to reach 3 in Q3 2026.

We invite scrutiny. The full rubric, source documentation, and per-dimension justification for every product (Headlights included) lives in this repository.

## Methodology limitations

- The scorecard scores **public posture**, not actual implementation quality. A vendor may have stronger internal practices than they document publicly; we do not credit what we cannot read.
- The scorecard scores **the product as documented at the date of the snapshot**. Vendor capabilities change quickly. Quarterly re-scoring is the mitigation.
- The scorecard does not score **operational security** (key management, access controls, breach history) — those matter, but they are outside the conduct-record question.
- The scorecard does not score **AI safety, hallucination rates, alignment, or model capability** — those are distinct concerns with their own evaluation frameworks.

## Sources

Per-product source URLs are in `specs/scorecard-research.md`. The IETF AAT draft is at `https://datatracker.ietf.org/doc/html/draft-sharif-agent-audit-trail-00`.
