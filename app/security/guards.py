from __future__ import annotations

import re
import ipaddress
from typing import Any
from urllib.parse import urlsplit

from app.config.settings import settings


_SENSITIVE_ERROR = re.compile(
    r"(api[_-]?key|secret|password|token|authorization|credential|"
    r"database|postgres|redis://|smtp|traceback|file \"|\\\\)",
    re.IGNORECASE,
)


def public_error(exc: BaseException, fallback: str) -> str:
    """Return useful validation errors locally without exposing internals in production."""
    message = str(exc).strip()
    if settings.production_mode:
        return fallback
    if not message or len(message) > 240 or _SENSITIVE_ERROR.search(message):
        return fallback
    return message


def validate_provider_base_url(value: str) -> str:
    """Validate user-supplied provider endpoints before storing or calling them."""
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").strip().lower()
    except ValueError as exc:
        raise ValueError("Provider base URL is invalid") from exc
    if parsed.scheme not in {"https", "http"} or not host:
        raise ValueError("Provider base URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Provider base URL must not contain credentials")
    if settings.production_mode and parsed.scheme != "https":
        raise ValueError("Provider base URL must use HTTPS in production")
    blocked_names = {
        "localhost",
        "localhost.localdomain",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }
    if settings.production_mode and (host in blocked_names or host.endswith(".local")):
        raise ValueError("Provider base URL must not target a local network host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if settings.production_mode and address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        raise ValueError("Provider base URL must not target a private network address")
    return raw


def csrf_is_valid(request: Any) -> bool:
    """Validate the double-submit token for browser requests authenticated by cookie."""
    if not settings.csrf_enabled or request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if request.headers.get("Authorization", "").lower().startswith("bearer "):
        return True
    if not request.cookies.get("ascg_access_token"):
        return True
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get(settings.csrf_header_name, "")
    if not cookie_token or not header_token:
        return False
    import secrets
    return secrets.compare_digest(cookie_token, header_token)


def redacted_redis_config() -> dict[str, Any]:
    return {
        "connected": False,
        "host": settings.redis_host,
        "port": settings.redis_port,
    }


__all__ = [
    "csrf_is_valid",
    "public_error",
    "redacted_redis_config",
    "validate_provider_base_url",
]
