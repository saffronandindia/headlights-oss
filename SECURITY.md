# Security Policy

Headlights produces evidence that real institutions may one day rely on in front of a regulator or a court. Security issues in the chain primitive, the SDK, the verifier or the reference server can therefore matter more than the line count suggests. We take reports seriously.

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.0a*` (current pre-launch alpha) | Yes |
| Older snapshots | No |

Once we cut a `0.1.0` release, this table will track the supported branches.

## Cryptographic algorithms in scope

Headlights uses **ECDSA over the NIST P-256 curve** for record signatures, **SHA-256** for the hash chain and signature digests, and **IEEE P1363** fixed-length r||s encoding (not ASN.1 DER) for signature serialisation. The canonical record form is **JCS (RFC 8785)** JSON. The Merkle anchor uses **SHA-256** with **RFC 6962-style** odd-leaf duplication.

Reports of weaknesses in our implementation or use of any of these primitives are in scope.

## Reporting a vulnerability

Please email **security@useheadlights.com** with a description of the issue, steps to reproduce, the version or commit hash you tested against, and any proof-of-concept you have.

**Do not file public GitHub issues for security vulnerabilities** and please do not disclose the issue publicly until we have published a fix.

If you would like to encrypt your report, request a PGP key in your first message and we will provide one before you send any sensitive details.

## What's in scope

- The chain primitive in `chain/` (hash construction, signature verification, append rules, tamper-detection logic).
- The verifier CLI in `verifier/` (correctness of the verification path, refusal to accept malformed input).
- The Python SDK in `sdk-python/` (record construction, key handling, replay or injection resistance).
- The reference server in `server/` (authentication, authorisation, storage integrity, public endpoints).
- Anything that would let a third party forge, alter, replay or silently drop records in a chain.

## What's out of scope

- Bugs that require pre-existing administrative access on the host machine running the SDK.
- Issues in dependencies that have not been fixed upstream yet (please report upstream as well; we will track once an upstream fix exists).
- Social-engineering or phishing scenarios that do not involve a flaw in Headlights code.
- Denial-of-service attacks against the public hosted endpoints (these are rate-limited at the edge; vulnerability reports about specific exploitable amplification paths are still welcome).

## Response targets

- **Acknowledgement** within 2 business days (Melbourne time).
- **Triage and initial assessment** within 5 business days.
- **Coordinated fix and disclosure timeline** agreed with the reporter, typically within 30 days for non-critical issues and as fast as practical for actively-exploited ones.

## Recognition

We are happy to credit reporters in the release notes for the fix. If you would prefer to remain anonymous, please say so in your initial report.
