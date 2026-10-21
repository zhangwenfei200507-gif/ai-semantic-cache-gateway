from __future__ import annotations

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):

    id: int

    email: EmailStr

    is_active: bool

    is_verified: bool = True

    is_admin: bool

    created_at: str

    workspace: dict | None = None


class AuthResponse(BaseModel):

    access_token: str

    token_type: str = "bearer"

    user: UserResponse
