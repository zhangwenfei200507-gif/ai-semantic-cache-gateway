from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CacheEntry:

    key: str

    answer: str

    similarity: Optional[float] = None

    distance: Optional[float] = None

    created_at: Optional[int] = None

    hit_count: int = 0