"""Authentication and user schemas."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class UserPublic(ORMModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    team: Optional[str] = None
    is_active: bool
    last_login_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserPublic
    permissions: List[str]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="ANALYST", pattern="^(ANALYST|ADMIN)$")
    team: Optional[str] = "AML Operations"


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    role: Optional[str] = Field(default=None, pattern="^(ANALYST|ADMIN)$")
    team: Optional[str] = None
    is_active: Optional[bool] = None
