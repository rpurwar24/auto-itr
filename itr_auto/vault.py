"""Encryption-at-rest for stored secrets (bank PDF passwords).

The app is git-shareable and workspaces can be zipped/copied, so passwords must not sit on
disk in plaintext. Values are stored as `enc:<fernet-token>`; the key lives OUTSIDE the repo
(~/.config/itr-util/key.txt, chmod 600) so it never travels with a shared workspace.

Backward-compatible: `decrypt()` passes any non-`enc:` value straight through, so an existing
plaintext personal.json (and the test fixtures) keep working. The key file is created lazily
on first `encrypt()`, so read-only/plaintext paths never touch it.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:"
_KEY_PATH = Path(os.environ.get("ITR_KEY_FILE",
                                Path.home() / ".config" / "itr-util" / "key.txt"))


def _key() -> bytes:
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes().strip()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    k = Fernet.generate_key()
    _KEY_PATH.write_bytes(k)
    try:
        os.chmod(_KEY_PATH, 0o600)
    except OSError:
        pass
    return k


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    if not plaintext or is_encrypted(plaintext):
        return plaintext or ""
    return _PREFIX + Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt(value: str) -> str:
    """enc: values -> plaintext; anything else returned unchanged (plaintext passthrough)."""
    if not is_encrypted(value):
        return value or ""
    try:
        return Fernet(_key()).decrypt(value[len(_PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        return ""
