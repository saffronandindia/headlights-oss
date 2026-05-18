"""Canonicalisation and hashing helpers.

The hash chain in AAT §4.1 is defined over JCS-canonicalised (RFC 8785) JSON
serialisations of records. This module is the single place that knows how to
produce the canonical byte string and how to fold it through SHA-256.

Two things matter and they are easy to get wrong:

1. The bytes hashed for the *signature* are the canonical form of the record
   *without* the `signature` field.
2. The bytes hashed for the *chain* (`prev_hash` of the next record) are the
   canonical form of the *complete* record, *including* its `signature` field
   if present.

Helpers below are explicit about which one they compute.
"""

from __future__ import annotations

import hashlib
from typing import Any

import rfc8785

# AAT §4.1: "Encode the resulting 32-byte hash as a 64-character lowercase
# hexadecimal string."
HASH_HEX_LENGTH = 64


def canonical_bytes(record_dict: dict[str, Any]) -> bytes:
    """Return the JCS (RFC 8785) canonical byte form of a record dict.

    The caller is responsible for omitting or including the `signature` field
    according to which hash they intend to compute.
    """
    return rfc8785.dumps(record_dict)


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest, 64 characters."""
    return hashlib.sha256(data).hexdigest()


def sha256_raw(data: bytes) -> bytes:
    """Return the raw 32-byte SHA-256 digest.

    AAT §6.3 uses raw digests (not hex) when computing the session_hash from
    concatenated prev_hash values.
    """
    return hashlib.sha256(data).digest()


def record_hash_for_chain(record_dict: dict[str, Any]) -> str:
    """Compute the hex SHA-256 that the *next* record will reference as `prev_hash`.

    Per AAT §4.1, this is the hash over the *complete* canonical record,
    including the `signature` field if one was attached.
    """
    return sha256_hex(canonical_bytes(record_dict))


def record_hash_for_signing(record_dict: dict[str, Any]) -> bytes:
    """Return the SHA-256 digest (raw bytes) that an ECDSA P-256 signature
    must cover.

    Per AAT §4.2, this is the canonical hash of the record *without* its
    `signature` field. The caller passes a dict that does not contain a
    `signature` key.
    """
    if "signature" in record_dict:
        raise ValueError(
            "record_hash_for_signing called with a dict containing a 'signature' "
            "field. The signature hash must be computed over the record body "
            "with the signature field absent."
        )
    return sha256_raw(canonical_bytes(record_dict))


def is_valid_hex_hash(value: str) -> bool:
    """True if value is a 64-character lowercase hex string, per AAT §4.1."""
    if not isinstance(value, str) or len(value) != HASH_HEX_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()
