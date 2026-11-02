"""OTP, PIN and token primitives. Secrets are never stored in plain text."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta

from .models import now

# Server-side secret for HMAC-ing OTPs and tokens. Set AGRISCOUT_SECRET in production.
SECRET = os.environ.get("AGRISCOUT_SECRET", "dev-only-secret-change-me").encode()

OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 3
ACCESS_TTL = timedelta(minutes=5)
SESSION_TTL = timedelta(hours=8)
OTP_REQUESTS_PER_WINDOW = 3
OTP_WINDOW = timedelta(minutes=10)


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str, salt: str) -> str:
    return hmac.new(SECRET, f"{salt}:{otp}".encode(), hashlib.sha256).hexdigest()


def check_otp(otp: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(otp, salt), expected_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.scrypt(pin.encode(), salt=salt.encode(), n=2**14, r=8, p=1).hex()


def new_salt() -> str:
    return secrets.token_hex(8)


def mask_mobile(mobile: str) -> str:
    return f"{mobile[:2]}{'X' * max(len(mobile) - 5, 0)}{mobile[-3:]}" if len(mobile) >= 6 else "XXXX"


def expired(ts) -> bool:
    return now() >= ts
