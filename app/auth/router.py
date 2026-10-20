from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from app.config.settings import settings

from .database import init_db

from .dependencies import (
    get_current_user,
)

from .schemas import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResendVerificationRequest,
    UserResponse,
    VerifyEmailRequest,
)

from .security import (
    create_access_token,
)

from .service import (
    authenticate,
    create_email_verification,
    create_password_reset,
    get_user,
    register,
    reset_password,
    verify_email,
)
from app.security.rate_limit import enforce_rate_limit
from app.security.guards import public_error


router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
)

logger = logging.getLogger(__name__)


def _user_response(
    user: dict,
) -> UserResponse:

    return UserResponse(
        id=user["id"],
        email=user["email"],
        is_active=user["is_active"],
        is_verified=user["is_verified"],
        is_admin=user["is_admin"],
        created_at=user["created_at"],
        workspace=user.get("workspace"),
    )


def _send_email(
    to_email: str,
    subject: str,
    body: str,
) -> None:

    from email.message import EmailMessage
    import smtplib

    if not settings.smtp_configured:
        raise RuntimeError(
            "SMTP is not configured"
        )

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = to_email

    message.set_content(body)

    if settings.smtp_use_tls:

        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=30,
        ) as server:

            server.starttls()

            server.login(
                settings.smtp_username,
                settings.smtp_password,
            )

            server.send_message(
                message
            )

    else:

        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=30,
        ) as server:

            server.login(
                settings.smtp_username,
                settings.smtp_password,
            )

            server.send_message(
                message
            )


def _verification_url(
    token: str,
) -> str:

    return (
        f"{settings.auth_frontend_url}"
        f"/verify-email?token={token}"
    )


def _reset_url(
    token: str,
) -> str:

    return (
        f"{settings.auth_frontend_url}"
        f"/reset-password?token={token}"
    )


@router.on_event("startup")
def startup_auth() -> None:

    init_db()


@router.post(
    "/register",
    response_model=UserResponse,
)
def register_user(
    data: RegisterRequest,
    request: Request,
) -> UserResponse:

    enforce_rate_limit(request, "auth-register", settings.auth_rate_limit_per_minute)

    try:

        user = register(
            str(data.email),
            data.password,
            settings.admin_email,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=public_error(exc, "Registration failed"),
        )

    token = create_email_verification(
        user["id"]
    )

    url = _verification_url(token)

    try:

        _send_email(
            user["email"],
            "Verify your AI Semantic Cache Gateway account",
            (
                "Welcome!\n\n"
                "Please verify your email address "
                "by opening this link:\n\n"
                f"{url}\n\n"
                "This link expires in 30 minutes."
            ),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Registration succeeded, "
                "but verification email could not be sent."
            ),
        ) from exc

    return _user_response(user)


@router.post(
    "/verify-email",
)
def verify_email_endpoint(
    data: VerifyEmailRequest,
    request: Request,
) -> dict:

    enforce_rate_limit(request, "auth-verify", settings.auth_rate_limit_per_minute)

    if not verify_email(
        data.token
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    return {
        "message": "Email verified successfully"
    }


@router.post(
    "/resend-verification",
)
def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
) -> dict:

    enforce_rate_limit(request, "auth-resend", settings.auth_rate_limit_per_minute)

    user = None

    from .database import get_connection

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (
                str(data.email).strip().lower(),
            ),
        ).fetchone()

    if row:

        user = {
            "id": row["id"],
            "email": row["email"],
            "is_verified": bool(
                row["is_verified"]
            ),
        }

    # Do not reveal whether the account exists.

    if user and not user["is_verified"]:

        token = create_email_verification(
            user["id"]
        )

        url = _verification_url(
            token
        )

        try:

            _send_email(
                user["email"],
                "Verify your email address",
                (
                    "Please verify your email address:\n\n"
                    f"{url}\n\n"
                    "This link expires in 30 minutes."
                ),
            )

        except Exception as exc:
            # Keep SMTP credentials and provider responses out of logs while making
            # delivery failures diagnosable in the deployment logs.
            logger.warning(
                "Verification email delivery failed: error_type=%s smtp_code=%s",
                type(exc).__name__,
                getattr(exc, "smtp_code", None),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Verification email delivery is temporarily unavailable. Try again later.",
            ) from None

    return {
        "message": (
            "If the email is registered and "
            "not verified, a verification email "
            "has been sent."
        )
    }


@router.post(
    "/login",
    response_model=AuthResponse,
)
def login_user(
    data: LoginRequest,
    response: Response,
    request: Request,
) -> AuthResponse:

    enforce_rate_limit(request, "auth-login", settings.auth_rate_limit_per_minute)

    try:

        user = authenticate(
            str(data.email),
            data.password,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=public_error(exc, "Authentication failed"),
        )

    if not user:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = create_access_token(
        user["id"],
        user["email"],
        user["is_admin"],
    )

    # Browser session: HttpOnly cookie. The frontend does not need to
    # manually attach a token for normal authenticated page/API calls.
    response.set_cookie(
        key="ascg_access_token",
        value=access_token,
        max_age=int(getattr(settings, "auth_token_expiration_hours", 24)) * 3600,
        httponly=True,
        samesite=str(settings.cookie_samesite).lower(),
        secure=settings.effective_cookie_secure,
        path="/",
    )
    import secrets
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=secrets.token_urlsafe(32),
        max_age=int(getattr(settings, "auth_token_expiration_hours", 24)) * 3600,
        httponly=False,
        samesite=str(settings.cookie_samesite).lower(),
        secure=settings.effective_cookie_secure,
        path="/",
    )

    return AuthResponse(
        access_token=access_token,
        user=_user_response(user),
    )


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(
        key="ascg_access_token",
        path="/",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
    )
    return {"message": "Logged out successfully"}


@router.get(
    "/me",
    response_model=UserResponse,
)
def me(
    user: dict = Depends(
        get_current_user
    ),
) -> UserResponse:

    return _user_response(user)


@router.post(
    "/forgot-password",
)
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
) -> dict:

    enforce_rate_limit(request, "auth-forgot", settings.auth_rate_limit_per_minute)

    token = create_password_reset(
        str(data.email)
    )

    if token:

        url = _reset_url(token)

        try:

            _send_email(
                str(data.email),
                "Reset your AI Semantic Cache Gateway password",
                (
                    "A password reset was requested "
                    "for your account.\n\n"
                    "Open this link to reset your password:\n\n"
                    f"{url}\n\n"
                    "This link expires in 30 minutes.\n\n"
                    "If you did not request this, "
                    "you can ignore this email."
                ),
            )

        except Exception:
            # Do not expose account information.
            pass

    return {
        "message": (
            "If the email is registered, "
            "a password reset email has been sent."
        )
    }


@router.post(
    "/reset-password",
)
def reset_password_endpoint(
    data: ResetPasswordRequest,
    request: Request,
) -> dict:

    enforce_rate_limit(request, "auth-reset", settings.auth_rate_limit_per_minute)

    if not reset_password(
        data.token,
        data.new_password,
    ):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    return {
        "message": "Password reset successfully"
    }
