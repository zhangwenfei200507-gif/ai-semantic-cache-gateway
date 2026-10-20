from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.history.request_history import request_history


router = APIRouter(
    prefix="/api/requests",
    tags=["request-history"],
)


@router.get("")
def list_requests(
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    search: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    cache_type: str | None = None,
    status: str | None = None,
    cache_hit: bool | None = None,
    min_similarity: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
    ),
    max_similarity: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
    ),
) -> dict[str, Any]:
    return request_history.list(
        page=page,
        page_size=page_size,
        search=search,
        model=model,
        provider=provider,
        cache_type=cache_type,
        status=status,
        cache_hit=cache_hit,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
    )


@router.get("/stats")
def request_stats() -> dict[str, Any]:
    return request_history.stats()


@router.get("/search")
def search_requests(
    q: str = Query(
        min_length=1,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
) -> dict[str, Any]:
    records = request_history.search(
        q,
        limit=limit,
    )

    return {
        "query": q,
        "items": [
            record.to_dict()
            for record in records
        ],
        "total": len(records),
    }


@router.get("/{request_id}")
def get_request(
    request_id: str,
) -> dict[str, Any]:
    record = request_history.get(
        request_id
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Request record not found",
        )

    return record.to_dict()


@router.delete("")
def clear_request_history() -> dict[str, Any]:
    request_history.clear()

    return {
        "status": "ok",
        "size": 0,
    }