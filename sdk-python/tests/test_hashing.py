"""Tests for the SDK's input/output hashing helpers."""

from __future__ import annotations

import hashlib

from headlights_sdk.hashing import hash_call_inputs, hash_value


def test_hash_value_is_stable_across_dict_key_order() -> None:
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert hash_value(a) == hash_value(b)


def test_hash_value_distinguishes_different_content() -> None:
    assert hash_value({"x": 1}) != hash_value({"x": 2})


def test_hash_value_falls_back_for_non_json_objects() -> None:
    class Custom:
        def __repr__(self) -> str:
            return "Custom(1)"

    h1 = hash_value(Custom())
    h2 = hash_value(Custom())
    assert h1 == h2  # repr is stable
    assert len(h1) == 64


def test_hash_call_inputs_distinguishes_args_vs_kwargs() -> None:
    a = hash_call_inputs(("x",), {})
    b = hash_call_inputs((), {"x": "x"})
    assert a != b


def test_hash_call_inputs_stable_kwargs_order() -> None:
    a = hash_call_inputs((), {"a": 1, "b": 2})
    b = hash_call_inputs((), {"b": 2, "a": 1})
    assert a == b


def test_hash_value_returns_64_char_lowercase_hex() -> None:
    h = hash_value("anything")
    assert len(h) == 64
    assert h == h.lower()
    int(h, 16)
