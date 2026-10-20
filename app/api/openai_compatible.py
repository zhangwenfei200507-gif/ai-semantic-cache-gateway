from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.openai_response import (
    to_openai_chat_completion,
)

from app.gateway import get_gateway
from app.auth.dependencies import get_current_user
from app.config.settings import settings
from app.security.guards import public_error
from app.security.rate_limit import enforce_rate_limit, workspace_concurrency


class ChatCompletionRequest(BaseModel):

    model: str = "auto"

    messages: list[dict[str, Any]] = Field(
        min_length=1
    )

    user: str | None = None

    stream: bool = False


router = APIRouter()


@router.post(
    "/v1/chat/completions"
)
def chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    user: dict = Depends(get_current_user),
):
    workspace_id = str(user["workspace"]["id"])
    enforce_rate_limit(
        http_request,
        "workspace-request",
        settings.workspace_request_rate_limit_per_minute,
        identity=f"workspace:{workspace_id}",
    )
    lease = workspace_concurrency.acquire(workspace_id)
    try:
        if request.stream:
            raise HTTPException(
                status_code=501,
                detail="Streaming is not implemented in this gateway stage.",
            )
        gateway = get_gateway()
        try:
            result = gateway.chat(
                messages=request.messages,
                model=request.model,
                user_id=str(user["id"]),
                workspace_id=workspace_id,
            )
            return to_openai_chat_completion(result)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=public_error(exc, "Invalid chat request"),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail=public_error(exc, "Upstream gateway request failed"),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream gateway request failed",
            ) from exc
    finally:
        lease.release()
