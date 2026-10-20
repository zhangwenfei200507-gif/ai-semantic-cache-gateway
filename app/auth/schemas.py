from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):

    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128,
    )


class LoginRequest(BaseModel):

    email: EmailStr

    password: str = Field(
        min_length=1,
        max_length=128,
    )


class ForgotPasswordRequest(BaseModel):

    email: EmailStr


class ResetPasswordRequest(BaseModel):

    token: str = Field(
        min_length=1,
    )

    new_password: str = Field(
        min_length=8,
        max_length=128,
    )


class VerifyEmailRequest(BaseModel):

    token: str = Field(
        min_length=1,
    )


class ResendVerificationRequest(BaseModel):

    email: EmailStr


class UserResponse(BaseModel):

    id: int

    email: EmailStr

    is_active: bool

    is_verified: bool

    is_admin: bool

    created_at: str

    workspace: dict | None = None


class AuthResponse(BaseModel):

    access_token: str

    token_type: str = "bearer"

    user: UserResponse
