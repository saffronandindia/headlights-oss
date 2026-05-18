"""Tests for ECDSA P-256 signatures with AAT §4.2 encoding."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from headlights_chain.signatures import (
    P1363_SIGNATURE_BYTES,
    SigningKey,
    VerifyingKey,
    _b64url_decode_nopad,
    _b64url_encode_nopad,
    generate_keypair,
)


def _digest(s: bytes) -> bytes:
    return hashlib.sha256(s).digest()


def test_generate_keypair_uses_p256() -> None:
    signing, verifying = generate_keypair()
    assert isinstance(signing, SigningKey)
    assert isinstance(verifying, VerifyingKey)
    assert isinstance(signing._private_key.curve, ec.SECP256R1)
    assert isinstance(verifying._public_key.curve, ec.SECP256R1)


def test_sign_verify_roundtrip() -> None:
    signing, verifying = generate_keypair()
    digest = _digest(b"hello world")
    sig = signing.sign_digest(digest)
    assert verifying.verify_digest(sig, digest) is True


def test_signature_is_64_byte_p1363_base64url() -> None:
    """AAT §4.2: signature is P1363 r||s (64 bytes), Base64url no padding."""
    signing, _ = generate_keypair()
    sig = signing.sign_digest(_digest(b"x"))
    raw = _b64url_decode_nopad(sig)
    assert len(raw) == P1363_SIGNATURE_BYTES
    assert "=" not in sig  # no padding


def test_verify_rejects_wrong_digest() -> None:
    signing, verifying = generate_keypair()
    sig = signing.sign_digest(_digest(b"original"))
    assert verifying.verify_digest(sig, _digest(b"tampered")) is False


def test_verify_rejects_wrong_key() -> None:
    signing_a, _ = generate_keypair()
    _, verifying_b = generate_keypair()
    sig = signing_a.sign_digest(_digest(b"x"))
    assert verifying_b.verify_digest(sig, _digest(b"x")) is False


def test_verify_rejects_garbage_signature() -> None:
    _, verifying = generate_keypair()
    assert verifying.verify_digest("not-a-real-signature", _digest(b"x")) is False
    assert verifying.verify_digest("", _digest(b"x")) is False


def test_verify_rejects_wrong_digest_length() -> None:
    signing, verifying = generate_keypair()
    sig = signing.sign_digest(_digest(b"x"))
    assert verifying.verify_digest(sig, b"short") is False


def test_sign_rejects_wrong_digest_length() -> None:
    signing, _ = generate_keypair()
    with pytest.raises(ValueError, match="32 bytes"):
        signing.sign_digest(b"too-short")


def test_pem_roundtrip_signing_key() -> None:
    signing, _ = generate_keypair()
    pem = signing.to_pem()
    restored = SigningKey.from_pem(pem)
    digest = _digest(b"x")
    sig_a = signing.sign_digest(digest)
    # Different randomness each sign; just check both verify
    assert signing.verifying_key.verify_digest(sig_a, digest)
    sig_b = restored.sign_digest(digest)
    assert restored.verifying_key.verify_digest(sig_b, digest)


def test_pem_roundtrip_verifying_key() -> None:
    signing, verifying = generate_keypair()
    pem = verifying.to_pem()
    restored = VerifyingKey.from_pem(pem)
    digest = _digest(b"x")
    sig = signing.sign_digest(digest)
    assert restored.verify_digest(sig, digest)


def test_pem_rejects_non_p256() -> None:
    # Generate a P-384 key and try to load it as a P-256 SigningKey.
    p384 = ec.generate_private_key(ec.SECP384R1())
    from cryptography.hazmat.primitives import serialization

    pem = p384.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="P-256"):
        SigningKey.from_pem(pem)


def test_b64url_helpers_roundtrip() -> None:
    for sample in [b"", b"x", b"\x00\xff", b"abc" * 11]:
        encoded = _b64url_encode_nopad(sample)
        assert "=" not in encoded
        assert _b64url_decode_nopad(encoded) == sample
