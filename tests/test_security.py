from __future__ import annotations

from api.app.security import hash_token, token_fingerprint, verify_token


def test_token_fingerprint_is_deterministic() -> None:
    t = "example-token"
    assert token_fingerprint(t) == token_fingerprint(t)
    assert token_fingerprint(t) != token_fingerprint(t + "-2")


def test_hash_and_verify_roundtrip() -> None:
    token = "super-secret-device-token"
    token_hash = hash_token(token)

    assert verify_token(token, token_hash) is True
    assert verify_token(token + "x", token_hash) is False
