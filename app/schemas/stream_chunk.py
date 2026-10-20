from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class StreamChunk:
    """
    Streaming LLM response chunk.

    Flow:

        Client
          |
        Provider
          |
        Gateway/API

    """

    content: str = ""

    model: str = ""

    provider: str = ""

    finish_reason: str | None = None

    raw: Any = None



    def to_dict(self) -> dict:

        return asdict(self)