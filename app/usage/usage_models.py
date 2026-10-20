from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Usage:
    """
    Unified token usage model.

    Represents one LLM call usage.
    """

    prompt_tokens: int = 0

    completion_tokens: int = 0


    @property
    def total_tokens(self) -> int:

        return (
            self.prompt_tokens
            +
            self.completion_tokens
        )


    def to_dict(self) -> dict:

        return {
            "prompt_tokens":
                self.prompt_tokens,

            "completion_tokens":
                self.completion_tokens,

            "total_tokens":
                self.total_tokens,
        }