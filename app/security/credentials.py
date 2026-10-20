from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings


class CredentialCipher:
    """Encrypt provider credentials without ever persisting plaintext keys."""

    @staticmethod
    def _fernet() -> Fernet:
        key = str(settings.provider_credential_encryption_key or "").strip()
        if not key:
            raise RuntimeError(
                "PROVIDER_CREDENTIAL_ENCRYPTION_KEY is required for BYOK"
            )
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError(
                "PROVIDER_CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key"
            ) from exc

    @classmethod
    def encrypt(cls, api_key: str) -> str:
        value = str(api_key or "").strip()
        if not value:
            raise ValueError("API key cannot be empty")
        return cls._fernet().encrypt(value.encode("utf-8")).decode("ascii")

    @classmethod
    def decrypt(cls, encrypted_api_key: str) -> str:
        try:
            return cls._fernet().decrypt(
                str(encrypted_api_key).encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise RuntimeError("Stored provider credential cannot be decrypted") from exc

    @staticmethod
    def fingerprint(api_key: str) -> str:
        return hashlib.sha256(str(api_key).encode("utf-8")).hexdigest()

    @staticmethod
    def mask(api_key: str | None) -> str | None:
        if not api_key:
            return None
        value = str(api_key)
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}{'*' * min(12, len(value) - 8)}{value[-4:]}"


def mask_api_key(api_key: str | None) -> str | None:
    return CredentialCipher.mask(api_key)


__all__ = ["CredentialCipher", "mask_api_key"]
