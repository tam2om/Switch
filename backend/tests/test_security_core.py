import pytest

from app.core.crypto import CryptoError, KeyRing, generate_key
from app.core.redact import MASK, redact, redact_text
from app.core.security import hash_password, password_policy_errors, verify_password


def test_argon2id_hash_and_verify():
    h = hash_password("Some-Strong-Pass-123")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Some-Strong-Pass-123")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "anything")


def test_password_policy():
    assert password_policy_errors("short")
    assert password_policy_errors("alllowercaseletters")
    assert any("common" in e for e in password_policy_errors("Password123"))
    assert any("username" in e for e in password_policy_errors("Alice-Strong-99x", "alice"))
    assert password_policy_errors("Correct-Horse-Battery-9") == []


def test_keyring_roundtrip_rotation_and_tamper():
    k1, k2 = generate_key(), generate_key()
    old = KeyRing.parse(f"a:{k1}")
    token = old.encrypt_str("secret-value", "aad1")
    assert "secret-value" not in token
    ring = KeyRing.parse(f"b:{k2},a:{k1}")  # rotated: new active key, old still decrypts
    assert ring.decrypt_str(token, "aad1") == "secret-value"
    assert ring.decrypt_str(ring.encrypt_str("x"), "") == "x"
    with pytest.raises(CryptoError):
        ring.decrypt_str(token, "other-aad")  # bound to context
    blob = bytearray(ring.encrypt_bytes(b"data"))
    blob[-1] ^= 1
    with pytest.raises(CryptoError):
        ring.decrypt_bytes(bytes(blob))
    with pytest.raises(CryptoError):
        KeyRing.parse("a:tooshort")


def test_secret_masking():
    data = {"username": "ops", "password": "p@ss", "nested": {"auth_password": "x", "list": [{"key": "k"}]},
            "note": "snmpv3 user mon auth sha AuthPass1 priv aes PrivPass1"}
    out = redact(data)
    assert out["password"] == MASK and out["nested"]["auth_password"] == MASK
    assert out["nested"]["list"][0]["key"] == MASK
    assert "AuthPass1" not in out["note"] and "PrivPass1" not in out["note"]
    assert "hunter2" not in redact_text("password hunter2")
    assert "abc123" not in redact_text("Cookie: sessionId=abc123; path=/")
