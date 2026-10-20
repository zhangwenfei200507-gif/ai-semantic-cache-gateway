import hashlib
import json
from typing import Any


def hash_messages(messages: Any) -> str:
    """
    Create a stable SHA-256 hash for chat messages.

    The hash is used by the exact cache layer.

    The same logical messages should always produce
    the same cache key regardless of dictionary ordering.
    """

    normalized = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()