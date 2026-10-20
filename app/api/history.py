from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException


from app.history.repository import history_repository
from app.auth.dependencies import get_current_user
from app.storage.service import ImageAssetRepository
from app.security.guards import public_error


def _rough_tokens(text: str | None) -> int:
    if not text:
        return 0

    value = str(text)
    chinese = sum(
        1
        for char in value
        if "\u4e00" <= char <= "\u9fff"
    )
    latin = sum(
        1
        for char in value
        if char.isascii() and char.isalpha()
    )

    return max(1, int(chinese * 1.05 + latin / 4.0))


def _with_savings(record: dict, workspace_id: int | str | None = None) -> dict:
    result = dict(record)
    result["consumed_tokens"] = int(
        result.get("total_tokens") or 0
    )
    result["saved_tokens"] = (
        _rough_tokens(result.get("question"))
        + _rough_tokens(result.get("answer"))
        if result.get("cache_hit")
        else 0
    )
    result["net_tokens"] = result["consumed_tokens"]
    if workspace_id is not None and result.get("request_id"):
        assets = ImageAssetRepository().by_request(result["request_id"], workspace_id)
        result["images"] = [
            {
                "id": asset["id"],
                "url": f"/api/images/{asset['id']}",
                "download_url": f"/api/images/{asset['id']}/download",
                "mime_type": asset["mime_type"],
                "width": asset.get("width"),
                "height": asset.get("height"),
                "file_size": asset["file_size"],
            }
            for asset in assets
        ]
    return result



router = APIRouter(
    prefix="/api",
    tags=["history"],
)



@router.get("/history")
def get_history(
    limit: int = 50,
    user: dict = Depends(get_current_user),
):

    try:

        records = history_repository.list(
            limit=limit,
            user_id=str(user["id"]),
            workspace_id=user["workspace"]["id"],
        )


        return {
            "count": len(records),
            "items": [_with_savings(item, user["workspace"]["id"]) for item in records],
        }


    except Exception as exc:

        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "History service unavailable"),
        ) from exc




@router.get("/history/{request_id}")
def get_history_detail(
    request_id: str,
    user: dict = Depends(get_current_user),
):

    try:

        record = (
            history_repository.get(
                request_id,
                user_id=str(user["id"]),
                workspace_id=user["workspace"]["id"],
            )
        )


        if record is None:

            raise HTTPException(
                status_code=404,
                detail="History record not found",
            )


        return _with_savings(record, user["workspace"]["id"])


    except HTTPException:

        raise


    except Exception as exc:

        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "History service unavailable"),
        ) from exc




@router.delete("/history")
def clear_history(user: dict = Depends(get_current_user)):

    try:

        workspace_id = user["workspace"]["id"]
        history_repository.clear(
            user_id=str(user["id"]),
            workspace_id=workspace_id,
        )
        from app.storage import get_image_asset_service

        removed_images = get_image_asset_service().clear_workspace(workspace_id)


        return {

            "status":
                "ok",

            "message":
                "history cleared",

            "images_removed":
                removed_images,

        }


    except Exception as exc:

        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "History service unavailable"),
        ) from exc
