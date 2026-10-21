from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config.settings import settings


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
