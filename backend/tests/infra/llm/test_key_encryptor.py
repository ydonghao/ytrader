"""Unit tests for AES key encryptor."""
import importlib.util
import os
import sys

import pytest

# Load the module directly from file to avoid triggering
# infra/__init__.py which eagerly imports heavy dependencies.
_backend_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
_module_path = os.path.join(
    _backend_root, "src", "infra", "llm", "key_encryptor.py"
)
_spec = importlib.util.spec_from_file_location(
    "src.infra.llm.key_encryptor", _module_path
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

KeyEncryptor = _mod.KeyEncryptor
generate_fernet_key = _mod.generate_fernet_key


def test_generate_fernet_key_returns_bytes():
    key = generate_fernet_key()
    assert isinstance(key, bytes)
    assert len(key) > 0


def test_generate_fernet_key_unique():
    key1 = generate_fernet_key()
    key2 = generate_fernet_key()
    assert key1 != key2


def test_encrypt_decrypt_roundtrip():
    encryptor = KeyEncryptor(generate_fernet_key())
    plaintext = "sk-test-api-key-12345"
    encrypted = encryptor.encrypt_key(plaintext)
    assert encrypted != plaintext
    decrypted = encryptor.decrypt_key(encrypted)
    assert decrypted == plaintext


def test_encrypt_produces_different_ciphertext():
    encryptor = KeyEncryptor(generate_fernet_key())
    plaintext = "same-key"
    enc1 = encryptor.encrypt_key(plaintext)
    enc2 = encryptor.encrypt_key(plaintext)
    assert enc1 != enc2


def test_decrypt_wrong_key_fails():
    enc1 = KeyEncryptor(generate_fernet_key())
    enc2 = KeyEncryptor(generate_fernet_key())
    encrypted = enc1.encrypt_key("secret")
    with pytest.raises(Exception):
        enc2.decrypt_key(encrypted)


def test_encrypt_empty_string():
    encryptor = KeyEncryptor(generate_fernet_key())
    encrypted = encryptor.encrypt_key("")
    assert encryptor.decrypt_key(encrypted) == ""
