from __future__ import annotations

import time
import uuid
from typing import Any

from app.schemas.gateway_response import (
    GatewayResponse,
)


def to_openai_chat_completion(
    result: GatewayResponse,
) -> dict[str, Any]:

    return {

        "id":
            f"chatcmpl-{uuid.uuid4().hex}",

        "object":
            "chat.completion",

        "created":
            int(time.time()),

        "model":
            result.model,

        "choices": [

            {

                "index":
                    0,

                "message": {

                    "role":
                        "assistant",

                    "content":
                        result.answer,

                },

                "finish_reason":
                    (
                        result.llm.finish_reason
                        or
                        "stop"
                    ),

            }

        ],

        "usage":
            result.usage,

        "cache": {

            "hit":
                result.cache_hit,

            "type":
                result.cache_type,

            "similarity":
                result.similarity,

            "threshold":
                result.threshold,

        },

        "gateway": {

            "request_id":
                (
                    result.context.request_id
                    if result.context
                    is not None
                    else
                    None
                ),

            "provider":
                result.provider,

            "model":
                result.model,

            "cost":
                result.cost,

            "latency_ms":
                result.latency_ms,

            "routing":
                result.routing,

        },

    }