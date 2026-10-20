from __future__ import annotations

import uuid


def create_request_id() -> str:
    """
    Create unique request id.
    """

    return str(uuid.uuid4())