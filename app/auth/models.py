from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class User:
    id: int
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime
