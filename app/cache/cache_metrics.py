from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class CacheMetrics:
    """
    Cache runtime metrics.

    Track:
        - request count
        - exact hit
        - semantic hit
        - miss
        - similarity statistics
    """

    total_requests: int = 0

    exact_hits: int = 0

    semantic_hits: int = 0

    misses: int = 0

    semantic_similarity_sum: float = 0.0

    semantic_similarity_count: int = 0

    best_similarity: float = 0.0


    def record_request(self) -> None:

        self.total_requests += 1



    def record_exact_hit(self) -> None:

        self.exact_hits += 1



    def record_semantic_hit(
        self,
        similarity: float | None = None,
    ) -> None:

        self.semantic_hits += 1

        if similarity is not None:

            value = float(similarity)

            self.semantic_similarity_sum += value

            self.semantic_similarity_count += 1

            if value > self.best_similarity:

                self.best_similarity = value



    def record_miss(self) -> None:

        self.misses += 1



    @property
    def hits(self) -> int:

        return (
            self.exact_hits
            +
            self.semantic_hits
        )



    @property
    def hit_rate(self) -> float:

        if self.total_requests == 0:

            return 0.0

        return round(
            self.hits /
            self.total_requests,
            4,
        )



    @property
    def average_similarity(self) -> float:

        if self.semantic_similarity_count == 0:

            return 0.0

        return round(
            self.semantic_similarity_sum /
            self.semantic_similarity_count,
            4,
        )



    def snapshot(self) -> Dict:

        return {

            "total_requests":
                self.total_requests,

            "exact_hits":
                self.exact_hits,

            "semantic_hits":
                self.semantic_hits,

            "misses":
                self.misses,

            "hit_rate":
                self.hit_rate,

            "average_similarity":
                self.average_similarity,

            "best_similarity":
                self.best_similarity,

        }



    def reset(self) -> None:

        self.total_requests = 0

        self.exact_hits = 0

        self.semantic_hits = 0

        self.misses = 0

        self.semantic_similarity_sum = 0.0

        self.semantic_similarity_count = 0

        self.best_similarity = 0.0