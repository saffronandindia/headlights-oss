"""Tests for canonicalisation and hashing helpers."""

from __future__ import annotations

import hashlib

import pytest

from headlights_chain.canonical import (
    HASH_HEX_LENGTH,
    canonical_bytes,
    is_valid_hex_hash,
    record_hash_for_chain,
    record_hash_for_signing,
    sha256_hex,
    sha256_raw,
)


def test_canonical_bytes_is_deterministic_under_key_reordering() -> None:
    """JCS sorts object keys; two dicts with the same content in different
    orders must produce identical canonical bytes."""
    a = {"b": 2, "a": 1, "c": 3}
    b = {"c": 3, "a": 1, "b": 2}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_canonical_bytes_distinguishes_different_content() -> None:
    a = {"k": "v1"}
    b = {"k": "v2"}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_sha256_hex_matches_hashlib() -> None:
    data = b"hello"
    assert sha256_hex(data) == hashlib.sha256(data).hexdigest()


def test_sha256_hex_is_lowercase_64_chars() -> None:
    h = sha256_hex(b"anything")
    assert len(h) == HASH_HEX_LENGTH
    assert h == h.lower()
    int(h, 16)  # must parse as hex


def test_sha256_raw_is_32_bytes() -> None:
    assert len(sha256_raw(b"x")) == 32


def test_record_hash_for_signing_rejects_dict_with_signature() -> None:
    """Spec invariant: signature covers the record body WITHOUT the signature
    field. The helper enforces this to keep callers honest."""
    with pytest.raises(ValueError, match="signature"):
        record_hash_for_signing({"foo": "bar", "signature": "abc"})


def test_record_hash_for_signing_returns_32_bytes() -> None:
    digest = record_hash_for_signing({"foo": "bar"})
    assert isinstance(digest, bytes)
    assert len(digest) == 32


def test_record_hash_for_chain_includes_signature() -> None:
    """The chain hash MUST cover the signature when one is present (AAT §4.1).
    A different signature must therefore produce a different chain hash."""
    base = {"foo": "bar"}
    h1 = record_hash_for_chain({**base, "signature": "sig-A"})
    h2 = record_hash_for_chain({**base, "signature": "sig-B"})
    h_unsigned = record_hash_for_chain(base)
    assert h1 != h2
    assert h1 != h_unsigned
    assert h2 != h_unsigned


def test_is_valid_hex_hash_accepts_64_lowercase_hex() -> None:
    h = sha256_hex(b"x")
    assert is_valid_hex_hash(h)


def test_is_valid_hex_hash_rejects_uppercase() -> None:
    h = sha256_hex(b"x").upper()
    assert not is_valid_hex_hash(h)


def test_is_valid_hex_hash_rejects_wrong_length() -> None:
    assert not is_valid_hex_hash("a" * 63)
    assert not is_valid_hex_hash("a" * 65)


def test_is_valid_hex_hash_rejects_non_hex() -> None:
    assert not is_valid_hex_hash("z" * 64)
    assert not is_valid_hex_hash("")
    assert not is_valid_hex_hash("not-hex")
