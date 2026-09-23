"""The Console's approval PIN: something a person knows that a browser agent does not.

Rules:
* the PIN is set and cleared only from an interactive terminal (`career-copilot pin`), never from
  an MCP tool or a Console route, so nothing driving the browser or the chat can choose its own;
* only a salted scrypt hash is stored, in the `meta` table; the PIN itself is never written anywhere,
  audit log included;
* when set, the Console asks for it on every approval and accepts it to unlock an idle-locked session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from .store import Store

META_KEY = "console_pin_hash"
MIN_LENGTH = 6
MAX_LENGTH = 12
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_ASCENDING = "0123456789"


class PinError(ValueError):
    pass


def validate(pin: str) -> str:
    """Return the PIN stripped of surrounding whitespace, or raise PinError saying what is wrong."""
    pin = pin.strip()
    if not pin.isascii() or not pin.isdigit():
        raise PinError("a PIN is digits only")
    if not MIN_LENGTH <= len(pin) <= MAX_LENGTH:
        raise PinError(f"a PIN is {MIN_LENGTH} to {MAX_LENGTH} digits long")
    if len(set(pin)) == 1:
        raise PinError("a PIN can't be one digit repeated")
    if pin in _ASCENDING or pin in _ASCENDING[::-1]:
        raise PinError("a PIN can't be a straight run like 123456")
    return pin


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_pin(pin: str) -> str:
    pin = validate(pin)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode("ascii"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify(pin: str, stored: str) -> bool:
    """Constant-time check of a PIN against a stored hash. A malformed hash never matches."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.scrypt(pin.strip().encode("utf-8"), salt=base64.b64decode(salt, validate=True),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def stored_hash(store: Store) -> str | None:
    return store.get_meta(META_KEY)


def is_set(store: Store) -> bool:
    return bool(stored_hash(store))


def set_pin(store: Store, pin: str) -> None:
    """Human-only: called from the CLI in an interactive terminal."""
    hashed = hash_pin(pin)
    replaced = is_set(store)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (META_KEY, hashed),
        )
        store.audit("human", "pin.set", "console", {"replaced": replaced}, conn=conn)


def clear_pin(store: Store) -> bool:
    """Human-only. Returns whether there was a PIN to clear."""
    with store.transaction() as conn:
        removed = conn.execute("DELETE FROM meta WHERE key = ?", (META_KEY,)).rowcount
        if removed:
            store.audit("human", "pin.clear", "console", {}, conn=conn)
    return bool(removed)
