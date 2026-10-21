from __future__ import annotations

from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from .security import (
    decode_access_token,
)

from .service import get_user


bearer = HTTPBearer(
    auto_error=False
)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer
    ),
) -> dict:

    # Prefer an explicit Bearer token when supplied.
    # Browser sessions also support the HttpOnly auth cookie, which
    # avoids fragile client-side token/header handling.
    token = None
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    else:
        token = request.cookies.get("ascg_access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:

        payload = decode_access_token(token)

        user_id = int(
            payload["sub"]
        )

    except (
        ValueError,
        KeyError,
        TypeError,
    ):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        )

    user = get_user(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User inactive",
        )

    return user


def get_current_admin(
    user: dict = Depends(
        get_current_user
    ),
) -> dict:

    if not user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )

    return user
