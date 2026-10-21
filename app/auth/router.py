from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.auth.database import init_db
from app.auth.dependencies import get_current_user
from app.auth.schemas import UserResponse
from app.auth.security import create_access_token
from app.auth.service import authenticate_oauth
from app.config.settings import settings


router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _user_response(user: dict) -> UserResponse:
    return UserResponse(
        id=user["id"],
        email=user["email"],
        is_active=user["is_active"],
        is_verified=True,
        is_admin=user["is_admin"],
        created_at=user["created_at"],
        workspace=user.get("workspace"),
    )


def _provider_config(provider: str) -> tuple[str, str] | None:
    provider = str(provider or "").strip().lower()
    if provider == "github":
        client_id = settings.github_oauth_client_id
        client_secret = settings.github_oauth_client_secret
    elif provider == "google":
        client_id = settings.google_oauth_client_id
        client_secret = settings.google_oauth_client_secret
    else:
        return None
    if not str(client_id or "").strip() or not str(client_secret or "").strip():
        return None
    return str(client_id).strip(), str(client_secret).strip()


def _redirect_uri(provider: str) -> str:
    return (
        f"{str(settings.auth_frontend_url).rstrip('/')}/api/auth/oauth/"
        f"{provider}/callback"
    )


def _login_url(error: str | None = None) -> str:
    base = str(settings.auth_frontend_url).rstrip("/")
    if base.endswith("/pages/login.html"):
        url = base
    else:
        url = f"{base}/pages/login.html"
    if error:
        url += "?" + urlencode({"oauth_error": error})
    return url


def _set_session(response: Response, user: dict) -> None:
    access_token = create_access_token(
        user["id"],
        user["email"],
        user["is_admin"],
    )
    max_age = int(getattr(settings, "auth_token_expiration_hours", 24)) * 3600
    response.set_cookie(
        key="ascg_access_token",
        value=access_token,
        max_age=max_age,
        httponly=True,
        samesite=str(settings.cookie_samesite).lower(),
        secure=settings.effective_cookie_secure,
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=secrets.token_urlsafe(32),
        max_age=max_age,
        httponly=False,
        samesite=str(settings.cookie_samesite).lower(),
        secure=settings.effective_cookie_secure,
        path="/",
    )


def _authorization_url(provider: str, state: str, client_id: str) -> str:
    redirect_uri = _redirect_uri(provider)
    if provider == "github":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        return "https://github.com/login/oauth/authorize?" + urlencode(params)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _exchange_code(provider: str, code: str, client_id: str, client_secret: str) -> dict:
    redirect_uri = _redirect_uri(provider)
    timeout = max(5.0, min(float(settings.smtp_timeout_seconds), 30.0))
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        if provider == "github":
            token_response = client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = str(token_payload.get("access_token") or "").strip()
            if not access_token:
                raise RuntimeError("GitHub did not return an access token")

            user_response = client.get(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
            user_response.raise_for_status()
            github_user = user_response.json()

            emails_response = client.get(
                "https://api.github.com/user/emails",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
            emails_response.raise_for_status()
            emails = emails_response.json()
            verified = [
                item for item in emails
                if item.get("verified") and item.get("email")
            ]
            email_row = next(
                (item for item in verified if item.get("primary")),
                verified[0] if verified else None,
            )
            if not email_row:
                raise RuntimeError("GitHub account has no verified email")
            return {
                "subject": str(github_user.get("id") or "").strip(),
                "email": str(email_row["email"]).strip().lower(),
                "email_verified": True,
            }

        token_response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Google did not return an access token")

        user_response = client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_response.raise_for_status()
        google_user = user_response.json()
        return {
            "subject": str(google_user.get("sub") or "").strip(),
            "email": str(google_user.get("email") or "").strip().lower(),
            "email_verified": bool(google_user.get("email_verified")),
        }


def _oauth_error(provider: str, exc: Exception) -> RedirectResponse:
    logger.warning(
        "OAuth login failed: provider=%s error_type=%s",
        provider,
        type(exc).__name__,
    )
    return RedirectResponse(_login_url("oauth_failed"), status_code=status.HTTP_303_SEE_OTHER)


@router.on_event("startup")
def startup_auth() -> None:
    init_db()


@router.get("/oauth/{provider}/start", include_in_schema=False)
def oauth_start(provider: str, request: Request) -> RedirectResponse:
    del request
    provider = str(provider).strip().lower()
    config = _provider_config(provider)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider.title()} OAuth is not configured",
        )

    state = secrets.token_urlsafe(32)
    redirect = RedirectResponse(
        _authorization_url(provider, state, config[0]),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    redirect.set_cookie(
        key="ascg_oauth_state",
        value=f"{provider}:{state}",
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.effective_cookie_secure,
        path="/api/auth/oauth",
    )
    return redirect


@router.get("/oauth/{provider}/callback", include_in_schema=False)
def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    provider = str(provider).strip().lower()
    if error:
        return RedirectResponse(_login_url("oauth_cancelled"), status_code=status.HTTP_303_SEE_OTHER)

    expected = request.cookies.get("ascg_oauth_state") or ""
    expected_provider, _, expected_state = expected.partition(":")
    if (
        provider not in {"github", "google"}
        or not code
        or not state
        or expected_provider != provider
        or not secrets.compare_digest(expected_state, state)
    ):
        return RedirectResponse(_login_url("oauth_state_invalid"), status_code=status.HTTP_303_SEE_OTHER)

    config = _provider_config(provider)
    if config is None:
        return RedirectResponse(_login_url("oauth_unavailable"), status_code=status.HTTP_303_SEE_OTHER)

    try:
        identity = _exchange_code(provider, code, config[0], config[1])
        if not identity["subject"] or not identity["email"]:
            raise RuntimeError("OAuth identity is incomplete")
        user = authenticate_oauth(
            provider,
            identity["subject"],
            identity["email"],
            bool(identity["email_verified"]),
        )
    except (httpx.HTTPError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return _oauth_error(provider, exc)

    redirect = RedirectResponse(
        _login_url(),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _set_session(redirect, user)
    redirect.delete_cookie("ascg_oauth_state", path="/api/auth/oauth")
    return redirect


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(key="ascg_access_token", path="/")
    response.delete_cookie(key=settings.csrf_cookie_name, path="/")
    response.delete_cookie(key="ascg_oauth_state", path="/api/auth/oauth")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def me(user: dict = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)


__all__ = ["router"]
