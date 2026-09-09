"""AES-256 key encryption using Fernet (cryptography library)."""
from __future__ import annotations

from cryptography.fernet import Fernet


def generate_fernet_key() -> bytes:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key()


class KeyEncryptor:
    """Encrypts and decrypts API keys using Fernet symmetric encryption."""

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt_key(self, plaintext: str) -> str:
        """Encrypt a plaintext API key. Returns base64-encoded ciphertext."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt_key(self, ciphertext: str) -> str:
        """Decrypt a ciphertext back to plaintext API key."""
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
