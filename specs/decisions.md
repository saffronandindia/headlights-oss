# Headlights — Architecture Decisions Record

Source of truth for foundational choices. Each decision has a status, a date, the alternatives considered, and the rationale. New decisions append to this file; superseded decisions are marked but not deleted.

Conventions:
- **Accepted** — current binding decision
- **Superseded** — replaced by a later decision (link forward)
- **Open** — known to need a decision but deferred

---

## ADR-001 — Align records with `draft-sharif-agent-audit-trail-00`

**Status:** Accepted — 2026-05-18
**Decision:** The on-disk and on-wire record format implements the IETF Agent Audit Trail (AAT) draft, version 00, by Raza Sharif (CyberSecAI Ltd), filed 2026-03-29.

**Caveat:** AAT-00 is an individual submission, not an adopted IETF work item. Datatracker explicitly states it has no formal IETF standing. We treat it as a vendor proposal we are aligning with, not a ratified standard.

**Rationale:**
- Standards alignment is free credibility — "Headlights implements the IETF AAT standard" reads strongly even when the standard is early.
- The spec is concrete enough to build against (fields, hash chain, canonicalisation, signature scheme all prescriptive).
- If/when AAT advances (-01, WG adoption), we update; if it stalls, we have lost nothing because our format remains self-coherent.
- Cite as `draft-sharif-agent-audit-trail-00` (work in progress) in public materials.

---

## ADR-002 — Chain scope is per-session, not per-agent or per-tenant

**Status:** Accepted — 2026-05-18
**Decision:** A single hash chain spans exactly one session, identified by `session_id` (UUIDv4). Genesis block has `action_type=lifecycle`, `action_detail.event=session_start`. Session close has `event=session_end` and contains the `session_hash` computed per AAT §6.3.

**Rationale:**
- AAT §6 mandates this — `session_id` binds records, `parent_record_id` chains them, and `session_hash` is defined only at session close.
- Per-agent chains would conflict with the spec and lead to unbounded chain growth.
- Per-tenant chains would conflate sessions and undermine the per-session integrity proof.
- Tenant isolation is enforced at the storage layer, not in the chain primitive. The record contains `agent_id` (URI) which our storage layer maps to a tenant; the chain itself is unaware of tenancy.
- Cross-session integrity is provided by anchoring a daily Merkle root of all `session_hash` values per tenant to Azure Immutable Blob Storage (ADR-005).

**Implication:** Long-running agents will produce many sessions. Session boundary policy (when to close + open a new one) is an SDK concern, not a chain concern. Default: 24-hour sessions, configurable.

---

## ADR-003 — Signature algorithm: ECDSA P-256, NOT Ed25519

**Status:** Accepted — 2026-05-18
**Decision:** Records that are signed use ECDSA P-256 per AAT §4.2, with IEEE P1363 r||s fixed-length 64-byte encoding (32 bytes r, 32 bytes s), Base64url-encoded per RFC 4648 §5.

**Supersedes:** The Headlights handover document v17 May 2026 stated "Ed25519 (per AAT draft)" — this was a misread of the spec. AAT-00 does not mention Ed25519 anywhere.

**Rationale:**
- AAT §4.2 is unambiguous: "records MAY include an ECDSA P-256 signature." No other algorithm is specified.
- Interop with any future AAT implementation requires P-256.
- FIPS 186-5 compliance is useful for the AU regulated mid-market story (APRA, OAIC) — Ed25519 is FIPS-approved as of 186-5 but ECDSA P-256 has the longer track record.
- Post-quantum migration (e.g. ML-DSA-65 used by Asqav) is deferred and would require an AAT extension introducing signature algorithm agility (e.g. an `alg` field). We do not unilaterally extend the spec.

---

## ADR-004 — Signatures are optional in the chain primitive, default ON in the SDK

**Status:** Accepted — 2026-05-18
**Decision:** The `chain` package supports records with or without a `signature` field. Records without signatures still chain correctly via `prev_hash`. The `sdk-python` package, when shipping, will default to signing every record using a tenant-provisioned key, with an explicit opt-out (`sign=False`).

**Rationale:**
- AAT §4.2: signatures are MAY, not MUST. The chain primitive must not violate spec by mandating them.
- Tamper-evidence (chain) and non-repudiation (signatures) are separable properties. We can ship tamper-evidence first, then layer signatures.
- The marketing/positioning claim is "every record signed by default" — achieved at the SDK level, not the chain level.
- Key management complexity (rotation, storage, recovery) belongs in the SDK and hosted platform, not in the chain primitive.

**Open question (deferred):** key identity binding. AAT-00 has no `key_id` field on records; verifiers must correlate the signing key to the agent via out-of-band metadata. We will track this in ADR-008 (TBD) once we have a concrete SDK key-management design.

---

## ADR-005 — External anchoring via daily Merkle root to Azure Immutable Blob Storage

**Status:** Accepted — 2026-05-18 (design only — implementation deferred to week 3-4 per handover)
**Decision:** Once per UTC day, the hosted platform computes a Merkle root over all `session_hash` values closed that day per tenant, and writes the root to a tenant-scoped Azure Immutable Blob Storage container with a legal-hold retention lock matching the tenant's retention setting (ADR-006). The root, the leaf list, and the blob commit URI are returned to the verifier on request.

**Rationale:**
- This provides a single anchor per tenant per day that can be independently verified against the public Azure storage record, defeating insider-tampering scenarios where database administrators could rewrite session chains.
- Daily granularity is a deliberate trade-off: more frequent anchors increase cost and verifier complexity; less frequent anchors widen the un-anchored window.
- Self-hosters can swap the anchor target (e.g. their own S3 Object Lock bucket, OpenTimestamps, a blockchain) by implementing the `Anchor` interface. The chain primitive does not know or care about anchoring.

---

## ADR-006 — Default retention: 7 years, configurable per tenant

**Status:** Accepted — 2026-05-18
**Decision:** Hosted platform defaults to 7-year retention on chain records and anchored Merkle roots. Configurable per tenant between 6 months (AAT-00 §7 general-purpose floor) and 10 years. Free tier capped at 30 days regardless of configuration.

**Rationale:**
- AU regulated mid-market is the target buyer. APRA CPS 234 / Privacy Act / OAIC record-keeping expectations are generally 7 years for financial records and IT security incidents.
- AAT §7 recommends 12 months for high-risk EU AI Act systems and 6 months for general purpose — 7 years comfortably clears both and matches the AU floor.
- Hosted Free tier (5 agents, 10K traces/month, 30-day retention per handover §11) cannot retain longer for cost reasons.

---

## ADR-007 — Asqav interop is deferred, not a launch commitment

**Status:** Accepted — 2026-05-18
**Decision:** Headlights does not claim interop with Asqav at launch. We will note Asqav as a peer SDK in the ecosystem map but make no mutual-verification commitment.

**Rationale:**
- Asqav uses ML-DSA-65 post-quantum signatures. AAT-00 mandates ECDSA P-256. The two are not signature-interoperable today.
- Asqav does not implement AAT.
- Interop would require either (a) AAT introducing signature agility (we cannot drive this unilaterally), or (b) Headlights and Asqav agreeing on a translation layer (out of scope for v1).
- Revisit if AAT-01 (or later) introduces an `alg` field or if Asqav adopts AAT.

---

## ADR-008 — Action-detail schema is permissive at v1, validated at v2

**Status:** Accepted — 2026-05-18
**Decision:** The `action_detail` object is typed as `dict[str, Any]` with no enforced per-`action_type` schema in v1. AAT §5 defines per-type required fields (e.g. `tool_call` requires `tool_name` and `parameters_hash`) — we will validate these in v2 once we have telemetry on what real agents emit.

**Rationale:**
- AAT §3.1: "Unknown fields within action_detail SHOULD be preserved by processors." Permissiveness is consistent with the spec.
- Premature schema validation will break integration with agents whose action vocabulary is unknown to us at launch.
- v2 adds a `--strict` flag to the SDK and verifier; v1 logs but does not reject non-conformant `action_detail` payloads.

---

## ADR-009 — JCS library: pin `rfc8785` (Python)

**Status:** Accepted — 2026-05-18
**Decision:** Use the `rfc8785` PyPI package for canonicalisation. Pin to `>=0.1.4,<0.2`. Re-evaluate when 1.0 is released.

**Rationale:**
- JCS (RFC 8785) is mandatory per AAT §4.1. Any implementation must match the spec exactly, especially around ECMA-262 number serialisation edge cases.
- `rfc8785` is the cleanest implementation we found; alternatives like `json-canonical` are less actively maintained.
- Cross-implementation determinism is non-negotiable: a verifier in Go or Rust must agree byte-for-byte on the canonical form. Library choice does not affect this, but library bugs do.

---

## Open decisions (tracked but not yet resolved)

- **OD-A.** Key rotation record structure. AAT §5.7 says "log via `lifecycle.event=key_rotation`" but does not specify which previous key signs the rotation record. Likely answer: the new key signs the rotation record, the new key's identity is recorded in `action_detail`, and the previous key is referenced in `action_detail.previous_key_fingerprint`. Defer to ADR when SDK key management is designed.
- **OD-B.** Tombstone validator semantics. AAT defines `event=record_deleted` with a `tombstone_hash` but does not specify exactly how verifiers should report the gap. Defer to verifier CLI design.
- **OD-C.** Clock source field name in genesis. AAT recommends recording the time source "when available" but does not name the field. Propose `action_detail.clock_source` ∈ {`ntp`, `tsa`, `roughtime`, `local`}.
- **OD-D.** Async batching semantics. AAT Appendix C.1 permits batching with implementer-defined ordering. Defer until we see real load patterns.
