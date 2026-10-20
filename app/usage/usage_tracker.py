from __future__ import annotations

from app.usage.usage_models import Usage



class UsageTracker:
    """
    Usage calculator.

    Responsibility:

        raw token data
              |
              v
          Usage object
    """


    def create(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Usage:


        return Usage(

            prompt_tokens=int(
                prompt_tokens or 0
            ),

            completion_tokens=int(
                completion_tokens or 0
            ),

        )



usage_tracker = UsageTracker()