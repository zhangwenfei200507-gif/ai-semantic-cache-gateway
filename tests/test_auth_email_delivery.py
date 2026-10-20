from __future__ import annotations

import smtplib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args):
        return _Cursor(self.row)


class VerificationEmailDeliveryTests(unittest.TestCase):
    def test_resend_reports_smtp_failure_without_exposing_credentials(self):
        from app.auth.router import resend_verification
        from app.auth.schemas import ResendVerificationRequest

        row = {"id": 17, "email": "user@example.com", "is_verified": False}
        smtp_error = smtplib.SMTPAuthenticationError(535, b"authentication failed")

        with (
            patch("app.auth.router.enforce_rate_limit"),
            patch("app.auth.database.get_connection", return_value=_Connection(row)),
            patch("app.auth.router.create_email_verification", return_value="token"),
            patch("app.auth.router._verification_url", return_value="https://example.test/verify"),
            patch("app.auth.router._send_email", side_effect=smtp_error),
        ):
            with self.assertRaises(HTTPException) as raised:
                resend_verification(
                    ResendVerificationRequest(email="user@example.com"),
                    SimpleNamespace(),
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertNotIn("authentication failed", str(raised.exception.detail).lower())
        self.assertNotIn("password", str(raised.exception.detail).lower())

    def test_resend_keeps_generic_success_response_when_delivery_succeeds(self):
        from app.auth.router import resend_verification
        from app.auth.schemas import ResendVerificationRequest

        row = {"id": 18, "email": "user@example.com", "is_verified": False}

        with (
            patch("app.auth.router.enforce_rate_limit"),
            patch("app.auth.database.get_connection", return_value=_Connection(row)),
            patch("app.auth.router.create_email_verification", return_value="token"),
            patch("app.auth.router._verification_url", return_value="https://example.test/verify"),
            patch("app.auth.router._send_email"),
        ):
            result = resend_verification(
                ResendVerificationRequest(email="user@example.com"),
                SimpleNamespace(),
            )

        self.assertIn("verification email", result["message"])


if __name__ == "__main__":
    unittest.main()
