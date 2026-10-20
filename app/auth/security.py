from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config.settings import settings


def hash_password(password: str) -> str:
    """
    PBKDF2 password hash.
    """

    salt = secrets.token_bytes(16)

    iterations = 310_000

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )

    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.urlsafe_b64encode(salt).decode()}"
        f"${base64.urlsafe_b64encode(digest).decode()}"
    )


def verify_password(
    password: str,
    encoded: str,
) -> bool:

    try:

        scheme, iterations, salt_b64, digest_b64 = (
            encoded.split("$")
        )

        if scheme != "pbkdf2_sha256":
            return False

        salt = base64.urlsafe_b64decode(
            salt_b64.encode()
        )

        expected = base64.urlsafe_b64decode(
            digest_b64.encode()
        )

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )

        return hmac.compare_digest(
            actual,
            expected,
        )

    except Exception:
        return False


def _b64(data: bytes) -> str:
    return (
        base64.urlsafe_b64encode(data)
        .rstrip(b"=")
        .decode()
    )


def _secret() -> bytes:

    value = getattr(
        settings,
        "auth_secret_key",
        None,
    )

    if not value:
        raise RuntimeError(
            "AUTH_SECRET_KEY is not configured"
        )

    return str(value).encode("utf-8")


def create_access_token(
    user_id: int,
    email: str,
    is_admin: bool = False,
    expires_seconds: int | None = None,
) -> str:

    if expires_seconds is None:
        expires_seconds = int(
            getattr(settings, "auth_token_expiration_hours", 24)
        ) * 3600

    now = int(time.time())

    header = _b64(
        json.dumps(
            {
                "alg": "HS256",
                "typ": "JWT",
            },
            separators=(",", ":"),
        ).encode()
    )

    payload = _b64(
        json.dumps(
            {
                "sub": str(user_id),
                "email": email,
                "is_admin": bool(is_admin),
                "iat": now,
                "exp": now + expires_seconds,
            },
            separators=(",", ":"),
        ).encode()
    )

    unsigned = (
        f"{header}.{payload}"
    ).encode()

    signature = _b64(
        hmac.new(
            _secret(),
            unsigned,
            hashlib.sha256,
        ).digest()
    )

    return (
        f"{header}.{payload}.{signature}"
    )


def decode_access_token(
    token: str,
) -> dict:

    try:

        header_b64, payload_b64, signature = (
            token.split(".")
        )

        unsigned = (
            f"{header_b64}.{payload_b64}"
        ).encode()

        expected = _b64(
            hmac.new(
                _secret(),
                unsigned,
                hashlib.sha256,
            ).digest()
        )

        if not hmac.compare_digest(
            signature,
            expected,
        ):
            raise ValueError(
                "Invalid token signature"
            )

        padding = "=" * (
            -len(payload_b64) % 4
        )

        payload = json.loads(
            base64.urlsafe_b64decode(
                (
                    payload_b64 + padding
                ).encode()
            ).decode()
        )

        if int(payload["exp"]) <= int(time.time()):
            raise ValueError(
                "Token expired"
            )

        return payload

    except Exception as exc:

        raise ValueError(
            "Invalid or expired access token"
        ) from exc


def create_secure_token() -> tuple[str, str]:

    raw = secrets.token_urlsafe(48)

    token_hash = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()

    return raw, token_hash


def create_reset_token() -> tuple[str, str]:
    return create_secure_token()


def create_verification_token() -> tuple[str, str]:
    return create_secure_token()
