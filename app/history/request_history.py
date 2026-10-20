from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class RequestRecord:
    """
    One completed gateway request record.

    This is intentionally process-local for the current stage.
    The interface is designed so Redis/database persistence can replace
    the storage implementation later without changing the API layer.
    """

    request_id: str
    created_at: float

    model: str
    provider: str

    question: str
    answer: str

    cache_hit: bool
    cache_type: str | None
    similarity: float | None

    latency_ms: float

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    cost: float

    status: str

    user_id: str | None = None
    finish_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)

        data["created_at"] = self.created_at

        return data


class RequestHistory:
    """
    In-memory request history repository.

    Responsibilities:
        - store completed request records
        - retrieve individual records
        - list records
        - filter records
        - search records
        - calculate summary statistics
        - keep storage bounded
    """

    def __init__(
        self,
        max_records: int = 5000,
    ) -> None:
        self.max_records = max(
            100,
            int(max_records),
        )

        self._records: list[RequestRecord] = []
        self._lock = threading.RLock()

    # =========================================================
    # Create
    # =========================================================

    def add(
        self,
        record: RequestRecord,
    ) -> RequestRecord:
        with self._lock:
            self._records.append(record)

            if len(self._records) > self.max_records:
                overflow = (
                    len(self._records)
                    - self.max_records
                )

                del self._records[:overflow]

        return record

    def create(
        self,
        *,
        model: str,
        provider: str,
        question: str,
        answer: str,
        cache_hit: bool,
        cache_type: str | None,
        similarity: float | None,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost: float,
        status: str,
        user_id: str | None = None,
        finish_reason: str | None = None,
        error: str | None = None,
        request_id: str | None = None,
    ) -> RequestRecord:
        record = RequestRecord(
            request_id=(
                request_id
                or f"req_{uuid.uuid4().hex}"
            ),
            created_at=time.time(),
            model=model,
            provider=provider,
            question=question,
            answer=answer,
            cache_hit=bool(cache_hit),
            cache_type=cache_type,
            similarity=(
                float(similarity)
                if similarity is not None
                else None
            ),
            latency_ms=float(latency_ms or 0.0),
            prompt_tokens=int(
                prompt_tokens or 0
            ),
            completion_tokens=int(
                completion_tokens or 0
            ),
            total_tokens=int(
                total_tokens or 0
            ),
            cost=float(cost or 0.0),
            status=status,
            user_id=user_id,
            finish_reason=finish_reason,
            error=error,
        )

        return self.add(record)

    # =========================================================
    # Read
    # =========================================================

    def get(
        self,
        request_id: str,
    ) -> RequestRecord | None:
        with self._lock:
            for record in reversed(self._records):
                if record.request_id == request_id:
                    return record

        return None

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        cache_type: str | None = None,
        status: str | None = None,
        cache_hit: bool | None = None,
        min_similarity: float | None = None,
        max_similarity: float | None = None,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = min(
            100,
            max(1, int(page_size)),
        )

        with self._lock:
            records = list(
                reversed(self._records)
            )

        filtered: list[RequestRecord] = []

        normalized_search = (
            search.strip().lower()
            if search
            else None
        )

        for record in records:
            if model:
                if record.model != model:
                    continue

            if provider:
                if record.provider != provider:
                    continue

            if cache_type:
                if (
                    record.cache_type or ""
                ).lower() != cache_type.lower():
                    continue

            if status:
                if record.status.lower() != status.lower():
                    continue

            if cache_hit is not None:
                if record.cache_hit != cache_hit:
                    continue

            if min_similarity is not None:
                if (
                    record.similarity is None
                    or record.similarity < min_similarity
                ):
                    continue

            if max_similarity is not None:
                if (
                    record.similarity is None
                    or record.similarity > max_similarity
                ):
                    continue

            if normalized_search:
                searchable = " ".join(
                    [
                        record.request_id,
                        record.model,
                        record.provider,
                        record.question,
                        record.answer,
                        record.user_id or "",
                    ]
                ).lower()

                if normalized_search not in searchable:
                    continue

            filtered.append(record)

        total = len(filtered)

        start = (
            page - 1
        ) * page_size

        end = start + page_size

        page_records = filtered[
            start:end
        ]

        pages = (
            (total + page_size - 1)
            // page_size
            if total
            else 0
        )

        return {
            "items": [
                record.to_dict()
                for record in page_records
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages,
            "has_next": page < pages,
            "has_previous": page > 1,
        }

    # =========================================================
    # Search
    # =========================================================

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[RequestRecord]:
        query = query.strip().lower()

        if not query:
            return []

        limit = min(
            100,
            max(1, int(limit)),
        )

        with self._lock:
            records = reversed(
                self._records
            )

            result: list[RequestRecord] = []

            for record in records:
                searchable = " ".join(
                    [
                        record.request_id,
                        record.model,
                        record.provider,
                        record.question,
                        record.answer,
                        record.user_id or "",
                    ]
                ).lower()

                if query in searchable:
                    result.append(record)

                    if len(result) >= limit:
                        break

        return result

    # =========================================================
    # Statistics
    # =========================================================

    def stats(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)

        total = len(records)

        if total == 0:
            return {
                "total_requests": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "exact_hits": 0,
                "semantic_hits": 0,
                "hit_rate": 0.0,
                "average_similarity": 0.0,
                "average_latency_ms": 0.0,
                "total_tokens": 0,
                "total_cost": 0.0,
            }

        cache_hits = sum(
            1
            for record in records
            if record.cache_hit
        )

        cache_misses = total - cache_hits

        exact_hits = sum(
            1
            for record in records
            if record.cache_type == "exact"
        )

        semantic_hits = sum(
            1
            for record in records
            if record.cache_type == "semantic"
        )

        similarity_values = [
            record.similarity
            for record in records
            if record.similarity is not None
        ]

        average_similarity = (
            sum(similarity_values)
            / len(similarity_values)
            if similarity_values
            else 0.0
        )

        average_latency = (
            sum(
                record.latency_ms
                for record in records
            )
            / total
        )

        total_tokens = sum(
            record.total_tokens
            for record in records
        )

        total_cost = sum(
            record.cost
            for record in records
        )

        return {
            "total_requests": total,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "exact_hits": exact_hits,
            "semantic_hits": semantic_hits,
            "hit_rate": round(
                cache_hits / total,
                4,
            ),
            "average_similarity": round(
                average_similarity,
                4,
            ),
            "average_latency_ms": round(
                average_latency,
                2,
            ),
            "total_tokens": total_tokens,
            "total_cost": round(
                total_cost,
                8,
            ),
        }

    # =========================================================
    # Maintenance
    # =========================================================

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._records)


request_history = RequestHistory()