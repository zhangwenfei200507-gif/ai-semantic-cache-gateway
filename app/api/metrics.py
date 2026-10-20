from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.auth.dependencies import get_current_admin


router = APIRouter()


@router.get("/metrics")
def metrics(_: dict = Depends(get_current_admin)):
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
