from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response

from app.auth.dependencies import get_current_user
from app.config.settings import settings
from app.storage import get_image_asset_service


router = APIRouter(prefix="/api/images", tags=["images"])


def _asset(asset_id: str, user: dict) -> tuple[object, dict]:
    service = get_image_asset_service()
    asset = service.get(asset_id, user["workspace"]["id"])
    if not asset:
        raise HTTPException(status_code=404, detail="Image not found")
    return service, asset


@router.get("/usage")
def image_usage(user: dict = Depends(get_current_user)):
    service = get_image_asset_service()
    usage = service.usage(user["workspace"]["id"])
    return {
        **usage,
        "max_count": int(settings.image_max_per_workspace),
        "max_bytes": int(settings.image_max_workspace_bytes),
    }


@router.get("/{asset_id}")
def preview_image(asset_id: str, user: dict = Depends(get_current_user)):
    service, asset = _asset(asset_id, user)
    try:
        content = service.content(asset)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Image storage is temporarily unavailable") from exc
    return Response(
        content=content,
        media_type=asset["mime_type"],
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{asset_id}/download")
def download_image(asset_id: str, user: dict = Depends(get_current_user)):
    service, asset = _asset(asset_id, user)
    signed_url = service.storage.presign(asset["object_key"])
    if signed_url:
        return RedirectResponse(signed_url, status_code=307)
    extension = asset["mime_type"].split("/", 1)[-1].replace("jpeg", "jpg")
    try:
        content = service.content(asset)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Image storage is temporarily unavailable") from exc
    return Response(
        content=content,
        media_type=asset["mime_type"],
        headers={
            "Content-Disposition": f'attachment; filename="generated-{asset_id}.{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{asset_id}")
def delete_image(asset_id: str, user: dict = Depends(get_current_user)):
    service = get_image_asset_service()
    if not service.delete(asset_id, user["workspace"]["id"]):
        raise HTTPException(status_code=404, detail="Image not found")
    return {"status": "ok", "id": asset_id}

