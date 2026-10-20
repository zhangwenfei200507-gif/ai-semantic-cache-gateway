from __future__ import annotations

from typing import Any


def _get_cache_service():
    """
    Lazy-load the cache service.

    Lazy loading prevents Redis / embedding dependencies from
    being imported during simple module inspection.
    """

    from app.cache.cache_service import (
        cache_service,
    )

    return cache_service


def save_cache(
    question: str,
    answer: str,
    model: str = "",
    tokens: int = 0,
    cost: float = 0.0,
    **kwargs: Any,
):
    """
    Compatibility wrapper for legacy cache calls.
    """

    service = _get_cache_service()

    method = getattr(
        service,
        "save",
        None,
    )

    if not callable(method):
        raise RuntimeError(
            "Cache service does not expose save()"
        )

    return method(
        question=question,
        answer=answer,
        model=model,
        tokens=tokens,
        cost=cost,
        **kwargs,
    )


def search_cache(
    question: str,
    model: str = "",
    **kwargs: Any,
):
    """
    Compatibility wrapper for legacy cache calls.
    """

    service = _get_cache_service()

    method = getattr(
        service,
        "search",
        None,
    )

    if not callable(method):
        raise RuntimeError(
            "Cache service does not expose search()"
        )

    return method(
        question=question,
        model=model,
        **kwargs,
    )


__all__ = [
    "save_cache",
    "search_cache",
]