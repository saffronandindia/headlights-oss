"""API key generation, hashing, and verification.

Keys look like `hl_live_<24 url-safe base64 chars>`. The server stores the
SHA-256 hash of the full key in the `api_keys` table along with a short prefix
for fast lookup. The plaintext key is shown exactly once at registration.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_api_key(prefix: str = "hl_live_") -> str:
    """Return a fresh API key. Format: `<prefix><24 url-safe chars>`."""
    return f"{prefix}{secrets.token_urlsafe(24)}"


def hash_api_key(key: str) -> str:
    """Return the lowercase hex SHA-256 of an API key, for storage."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_prefix(key: str, length: int = 16) -> str:
    """First `length` characters of the key, used as a fast-lookup index.

    Even with the prefix exposed, the secret part (the random suffix) still
    provides ~144 bits of entropy.
    """
    return key[:length]


def constant_time_equal(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return secrets.compare_digest(a.encode(), b.encode())
