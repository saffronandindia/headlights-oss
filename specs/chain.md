# Headlights Chain — Design Specification

**Status:** v0.1.0-alpha — genesis block landed 2026-05-18
**Implements:** [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/) (AAT)
**Package:** `chain/headlights_chain/`
**Related ADRs:** [decisions.md](decisions.md), in particular ADR-001 through ADR-009

This document specifies the on-disk record format, the hash chain mechanics, and the verification contract that the `headlights-chain` package implements. It is the source of truth for any future Headlights component — the Go verifier, the Node SDK, the hosted ingest pipeline — that needs to interoperate with the Python chain primitive byte-for-byte.

---

## 1. Scope

The chain primitive provides three properties:

1. **Tamper evidence.** Any modification, insertion, or deletion of a record after the fact is detectable by re-running `verify()` over the exported chain.
2. **Non-repudiation.** When records are signed (ADR-004), the signing key holder cannot credibly disown the record once it has been exported.
3. **Order integrity.** Records within a session are totally ordered, and the order is itself protected by the chain.

The chain primitive does NOT provide:

- **Confidentiality.** Records are plaintext. Sensitive material should be hashed (`input_hash`, `output_hash`, `parameters_hash`, etc.) before being added.
- **Availability.** That is the storage layer's concern.
- **Cross-session integrity.** A daily Merkle root anchored externally provides this (ADR-005), implemented above the chain primitive.
- **Tenancy.** Tenant separation is enforced at the storage layer (ADR-002).

---

## 2. Record format

Records are JSON objects. The schema is defined in [draft-sharif-agent-audit-trail-00 §3](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/) and is implemented by `headlights_chain.records.Record`.

### 2.1 Mandatory fields (AAT §3.1)

Always emitted in the canonical form, including when their value is `null`:

| Field | Type | Validation | Notes |
|---|---|---|---|
| `record_id` | string | UUIDv4 per RFC 9562 | Fresh per record |
| `timestamp` | string | RFC 3339 with mandatory UTC offset | Millisecond precision RECOMMENDED |
| `agent_id` | string | URI per RFC 3986 (light scheme check) | Must be persistent across restarts |
| `agent_version` | string | SemVer 2.0.0 | |
| `session_id` | string | UUIDv4 | Shared across all records in a session |
| `action_type` | string | Enum: `tool_call`, `tool_response`, `decision`, `delegation`, `escalation`, `error`, `lifecycle` | See `enums.ActionType` |
| `action_detail` | object | Non-empty | Per-type structure defined in AAT §5; not validated at v1 (ADR-008) |
| `outcome` | string | Enum: `success`, `failure`, `timeout`, `denied`, `escalated` | See `enums.Outcome` |
| `trust_level` | string | Enum: `L0`..`L4` | See `enums.TrustLevel` |
| `parent_record_id` | string or null | UUIDv4 if set | `null` only in genesis |
| `prev_hash` | string or null | 64-char lowercase hex SHA-256 if set | `null` only in genesis |

### 2.2 Optional fields (AAT §3.2)

Emitted only when set to a non-`None` value:

`human_override`, `risk_score` (0.0–1.0), `model_id`, `input_hash`, `output_hash`, `latency_ms`, `cost_estimate`, `sanctions_check`, `jurisdiction` (ISO 3166-1 alpha-2 uppercase), `signature` (Base64url-encoded P1363 ECDSA-P256 per §4 below).

### 2.3 Unknown / extra fields

Per AAT §3.1, unknown fields SHOULD be preserved by processors. The Pydantic model is configured with `extra="allow"`. Unknown fields are emitted in the canonical form when non-null. Field names prefixed `aat_` are reserved by the spec; the v1 chain primitive does not enforce this.

---

## 3. Canonicalisation

All hashing operates on the JSON Canonicalization Scheme (JCS) byte form of records, defined in RFC 8785. We use the `rfc8785` Python package pinned to `>=0.1.4,<0.2` (ADR-009).

The canonical form of a record is produced by `Record.to_canonical_dict()` followed by `rfc8785.dumps()`. The dict construction rules are:

1. Emit every mandatory field, in the spec-recommended order shown in §2.1 above. (Order does not matter for JCS — it sorts keys lexicographically — but a documented order helps debugging.)
2. Emit every optional field whose value is not `None`.
3. Emit every unknown extra field (preserved per AAT §3.1).
4. The `signature` field is treated specially (see §4).

The output of `rfc8785.dumps()` is the byte sequence over which SHA-256 is computed.

---

## 4. Hash chain mechanics (AAT §4.1)

Two hashes matter and must not be confused.

### 4.1 Chain hash (`prev_hash` of the next record)

```
prev_hash(N) = lower_hex( SHA-256( JCS( record(N-1) ) ) )
```

Where `record(N-1)` is the **complete** previous record, **including** its `signature` field if one was attached. Encoded as a 64-character lowercase hex string.

Helper: `canonical.record_hash_for_chain(record_dict) -> str`.

### 4.2 Signature digest (covered by the signature itself)

```
signature_digest(R) = SHA-256( JCS( record_without_signature(R) ) )
```

The signing party hashes the canonical form of the record with the `signature` field **absent**, then signs the 32-byte digest with ECDSA P-256. The resulting signature is inserted into the record's `signature` field, and the *complete* record (now including the signature) is what the next record's `prev_hash` covers.

Helper: `canonical.record_hash_for_signing(record_dict) -> bytes`. This helper raises `ValueError` if called with a dict containing a `signature` field — the contract is enforced rather than commented.

### 4.3 Genesis block

The first record in a session has:

- `parent_record_id = null`
- `prev_hash = null`
- `action_type = "lifecycle"`
- `action_detail.event = "session_start"`

It SHOULD additionally include `config_hash`, `enabled_tools`, and `operating_parameters` in `action_detail`. The `Chain.genesis(...)` factory accepts a `genesis_detail` dict and merges these in.

### 4.4 Session close (AAT §6.3)

The final record in a session is a `lifecycle` record with `action_detail.event = "session_end"`. It carries:

| Sub-field | Computation |
|---|---|
| `session_hash` | `lower_hex( SHA-256( raw_prev_hash_1 ‖ raw_prev_hash_2 ‖ … ‖ raw_prev_hash_N ) )` where `N` is the close record itself. Concatenation is of **raw 32-byte SHA-256 digests**, NOT their hex forms. |
| `record_count` | Total records in the session, including genesis and the close record |
| `duration_ms` | RECOMMENDED, not yet emitted by `Chain.close()`; planned for v0.2 |

`Chain.close()` writes this record. `Chain.is_closed` becomes `True` afterwards and further appends raise `RuntimeError`.

---

## 5. Signatures (AAT §4.2)

### 5.1 Algorithm

ECDSA over the NIST P-256 curve (FIPS 186-5). This is the only algorithm AAT-00 specifies. Ed25519 is NOT supported (ADR-003 supersedes the contrary note in the project handover).

### 5.2 Encoding

- Pre-hash with SHA-256 over the JCS canonical bytes of the record body (signature absent).
- Sign the 32-byte digest with ECDSA P-256 (`ECDSA(Prehashed(SHA256))` in `cryptography`).
- The library returns DER. Convert to IEEE P1363 fixed-length r||s, 64 bytes total (32 r, 32 s).
- Encode as Base64url per RFC 4648 §5, **no padding**.

This is the wire format mandated by AAT §4.2.

### 5.3 When signatures are required

Signatures are MAY in AAT. The chain primitive treats them as optional — chains without signatures still verify, just without non-repudiation. ADR-004 commits the SDK to signing by default.

### 5.4 Key identity binding

AAT-00 has no `key_id` field on records. Verifiers must obtain the signing key out of band (e.g. from the agent's Agent Passport per MCPS, or from a Headlights tenant key registry). Open question OD-A in `decisions.md` tracks key-rotation semantics.

---

## 6. Verification contract

`Chain.verify(verifying_key=None) -> VerificationResult`.

The verifier walks the chain from genesis to last record and checks, at each position:

1. **Genesis invariants** at position 0: `parent_record_id` and `prev_hash` are `null`, `action_type` is `lifecycle`, `action_detail.event` is `session_start`.
2. **Session identity:** `session_id` matches the genesis.
3. **Agent identity:** `agent_id` matches the genesis.
4. **Parent linkage:** at positions ≥1, `parent_record_id` equals the previous record's `record_id`.
5. **Chain hash:** at positions ≥1, `prev_hash` equals `record_hash_for_chain(previous_record)`.
6. **Timestamp monotonicity:** record `N+1`'s timestamp is greater than or equal to record `N`'s (AAT §3.3). Lexicographic compare on RFC 3339 with UTC offsets agrees with chronological order.
7. **Signature** (if `record.signature` is present AND `verifying_key` was supplied): `verify_digest(signature, signing_digest)` returns True.

If the chain `is_closed`, the verifier also recomputes the `session_hash` and `record_count` claims and compares them.

The result is the first failing position, or `VerificationResult.ok()` if every check passes.

### 6.1 Failure resolution order

For a single tampered record, multiple checks can fail. The verifier short-circuits on the first failure within each position, scanning positions in order. Common cases:

| What was tampered | First failing position | Failure reason |
|---|---|---|
| `action_detail` of record N (no signature) | N+1 | `prev_hash mismatch` |
| `action_detail` of record N (with signature) | N | `signature failed to verify` |
| `record_id` of record N | N+1 | `parent_record_id chain broken` |
| `signature` only | N | `signature failed to verify` |
| `session_hash` only (close record) | last | `session_hash mismatch` |
| `timestamp` rolled backwards | N | `prev_hash mismatch` (canonical form changed) or `timestamp regression` |

---

## 7. Persistence contract

The `Chain` class does not touch any storage. Production usage will pair it with adapters that:

- Persist `chain.records()` to a database after each `append` / `close`.
- Stream `record.to_canonical_dict()` to an append-only log.
- Hand off the close-record's `session_hash` to the daily Merkle root job (ADR-005).

`Chain.export_records()` produces a `list[dict]` that is round-trippable through `Chain.from_records()`. The export is also the wire form the verifier CLI will consume (delivered as NDJSON, one record per line).

---

## 8. Threat model

Adversaries considered:

1. **Database insider.** Can rewrite any row. Defeated by chain re-verification — every post-tampering record's `prev_hash` or `parent_record_id` will fail.
2. **Application insider.** Can produce records that look plausible but are not signed by the agent's key. Defeated by signature verification when the verifying key is known to the verifier.
3. **Application insider with signing-key access.** Can produce coherent-looking forged records. Defeated only by the daily external Merkle anchor (ADR-005) — pre-anchor records cannot be retroactively replaced without breaking the public anchor.
4. **Replay across sessions.** Defeated by `session_id` consistency check across the chain.

Out of scope for the chain primitive:

- Network MITM (TLS responsibility).
- Compromise of the verifier itself.
- Quantum-capable adversaries against ECDSA P-256 (deferred per ADR-007 and the open Asqav question).

---

## 9. Test coverage

`pytest` against `chain/tests/` covers:

- `test_canonical.py` — JCS determinism under key reordering, hash function correctness, signing/chain-hash separation, hex validation.
- `test_signatures.py` — keypair generation, sign/verify round-trip, P1363 64-byte encoding, tamper rejection, PEM round-trip, curve-mismatch rejection.
- `test_records.py` — every field validator (UUIDv4, RFC 3339, SemVer, URI, hex hash, risk_score range, ISO 3166), genesis invariants, canonical dict construction, optional-field omission, extra-field preservation, enum coercion.
- `test_chain.py` — genesis, three-record append linkage, close + session_hash, append-after-close rejection, intact verification, tamper detection at multiple positions, signature tamper detection, export/import round-trip, timestamp monotonicity.

Latest result: **64 passed, 96 % line coverage** (2026-05-18).

The `examples/loan_analyser_demo.py` runs the full §11 launch demo end-to-end against the chain primitive.

---

## 10. Open issues for future work

- **OD-A** (key rotation record structure) — pending SDK key-management design.
- **OD-B** (tombstone validator semantics) — pending verifier CLI design.
- **OD-C** (clock source field naming) — propose `action_detail.clock_source ∈ {ntp, tsa, roughtime, local}`.
- **OD-D** (async batching ordering) — defer until load patterns known.
- **AAT-01 tracking** — if/when AAT advances past `-00`, reconcile and bump.
- **Cross-implementation conformance vectors** — produce a small set of canonical records + expected hashes for Go/Rust/Node implementers to test against.
- **`duration_ms` in close record** — straightforward; planned for v0.2.

---

## 11. Versioning

The Python package version (`__version__`) and the on-wire record format version (which tracks AAT) are independent:

- Package: `v0.1.0-alpha`, will bump per semver as the public Python API matures.
- Record format: aligned to `draft-sharif-agent-audit-trail-00`. The next bump happens only when AAT-01 (or successor) is published and we explicitly migrate.

A record's `action_detail` MAY include an `aat_version` field once we have published one for self-identifying records — but this is not in AAT-00 and we will not invent it unilaterally.
