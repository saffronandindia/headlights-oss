"""ECDSA P-256 signing and verification per AAT §4.2.

Encoding rules from the spec, in order of importance:

- Algorithm: ECDSA over the NIST P-256 curve (FIPS 186-5).
- Signature input: SHA-256 over the JCS canonical bytes of the record with
  the `signature` field absent.
- On-wire encoding: IEEE P1363 fixed-length r||s, 64 bytes total
  (32 bytes r, 32 bytes s), Base64url with NO padding per RFC 4648 §5.
- This is NOT ASN.1 DER. The `cryptography` library returns DER by default
  so we convert.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

CURVE = ec.SECP256R1()
P1363_COMPONENT_BYTES = 32  # 256-bit components
P1363_SIGNATURE_BYTES = 64


def _b64url_encode_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode_nopad(data: str) -> bytes:
    padding_needed = (-len(data)) % 4
    return base64.urlsafe_b64decode(data + ("=" * padding_needed))


def _der_to_p1363(der_sig: bytes) -> bytes:
    r, s = decode_dss_signature(der_sig)
    return r.to_bytes(P1363_COMPONENT_BYTES, "big") + s.to_bytes(
        P1363_COMPONENT_BYTES, "big"
    )


def _p1363_to_der(p1363_sig: bytes) -> bytes:
    if len(p1363_sig) != P1363_SIGNATURE_BYTES:
        raise ValueError(
            f"P1363 signature must be {P1363_SIGNATURE_BYTES} bytes, got {len(p1363_sig)}"
        )
    r = int.from_bytes(p1363_sig[:P1363_COMPONENT_BYTES], "big")
    s = int.from_bytes(p1363_sig[P1363_COMPONENT_BYTES:], "big")
    return encode_dss_signature(r, s)


@dataclass(frozen=True)
class SigningKey:
    """An ECDSA P-256 private key wrapped with our spec-conformant signer."""

    _private_key: ec.EllipticCurvePrivateKey

    def sign_digest(self, digest_32: bytes) -> str:
        """Sign a 32-byte SHA-256 digest. Returns Base64url(P1363 r||s).

        Per AAT §4.2 the implementer pre-hashes the canonical record body and
        signs the digest. We therefore use `ECDSA(Prehashed(SHA256))` so the
        library does not re-hash.
        """
        if len(digest_32) != 32:
            raise ValueError(f"digest must be 32 bytes, got {len(digest_32)}")

        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

        der = self._private_key.sign(
            digest_32,
            ec.ECDSA(Prehashed(hashes.SHA256())),
        )
        return _b64url_encode_nopad(_der_to_p1363(der))

    @property
    def verifying_key(self) -> "VerifyingKey":
        return VerifyingKey(self._private_key.public_key())

    def to_pem(self, password: bytes | None = None) -> bytes:
        encryption = (
            serialization.BestAvailableEncryption(password)
            if password
            else serialization.NoEncryption()
        )
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )

    @classmethod
    def from_pem(cls, pem: bytes, password: bytes | None = None) -> "SigningKey":
        key = serialization.load_pem_private_key(pem, password=password)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("PEM did not decode to an EC private key")
        if not isinstance(key.curve, ec.SECP256R1):
            raise ValueError(
                f"AAT §4.2 mandates P-256; got curve {key.curve.name}"
            )
        return cls(key)


@dataclass(frozen=True)
class VerifyingKey:
    """An ECDSA P-256 public key wrapped with our spec-conformant verifier."""

    _public_key: ec.EllipticCurvePublicKey

    def verify_digest(self, signature_b64url: str, digest_32: bytes) -> bool:
        """Verify a Base64url(P1363 r||s) signature against a 32-byte digest.

        Returns True on a valid signature, False on any failure mode. Does not
        raise — the chain verifier wants a clean bool to fold into a
        per-position pass/fail.
        """
        if len(digest_32) != 32:
            return False
        try:
            p1363 = _b64url_decode_nopad(signature_b64url)
            der = _p1363_to_der(p1363)
        except (ValueError, base64.binascii.Error):
            return False

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

        try:
            self._public_key.verify(
                der,
                digest_32,
                ec.ECDSA(Prehashed(hashes.SHA256())),
            )
            return True
        except InvalidSignature:
            return False

    def to_pem(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @classmethod
    def from_pem(cls, pem: bytes) -> "VerifyingKey":
        key = serialization.load_pem_public_key(pem)
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise ValueError("PEM did not decode to an EC public key")
        if not isinstance(key.curve, ec.SECP256R1):
            raise ValueError(
                f"AAT §4.2 mandates P-256; got curve {key.curve.name}"
            )
        return cls(key)


def generate_keypair() -> tuple[SigningKey, VerifyingKey]:
    """Generate a fresh ECDSA P-256 key pair."""
    private_key = ec.generate_private_key(CURVE)
    signing = SigningKey(private_key)
    return signing, signing.verifying_key
