from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


PASSWORD_SCHEME = "scrypt-v1"


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 10:
        raise ValueError("password must contain at least 10 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"{PASSWORD_SCHEME}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt_hex, expected_hex = encoded.split("$", 2)
        if scheme != PASSWORD_SCHEME:
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**14,
            r=8,
            p=1,
            dklen=32,
        )
        return hmac.compare_digest(candidate, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class DeviceApiKey:
    key_id: str
    secret: str

    @property
    def token(self) -> str:
        return f"aqk_{self.key_id}.{self.secret}"


def new_device_api_key() -> DeviceApiKey:
    return DeviceApiKey(key_id=secrets.token_hex(8), secret=secrets.token_urlsafe(32))


def parse_device_api_key(token: str) -> DeviceApiKey | None:
    if not token.startswith("aqk_") or "." not in token:
        return None
    key_id, secret = token[4:].split(".", 1)
    if len(key_id) != 16 or len(secret) < 32:
        return None
    return DeviceApiKey(key_id=key_id, secret=secret)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)

