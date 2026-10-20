from __future__ import annotations

from typing import Dict


class SimilarityScorer:
    """
    Semantic similarity scorer.

    The score is expected to be cosine similarity:

        1.0  -> identical / extremely similar
        0.8  -> very similar
        0.7  -> semantically related
        0.5  -> weak relationship
        0.0  -> unrelated

    Default threshold is 0.70 because the current
    BGE embedding model + Redis COSINE search produces
    approximately 0.72 for:

        Kafka是什么
        请简单介绍一下Kafka
    """

    DEFAULT_THRESHOLD = 0.70

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        threshold = float(threshold)

        if not 0.0 <= threshold <= 1.0:
            raise ValueError(
                "threshold must be between 0.0 and 1.0"
            )

        self.threshold = threshold

    def score(
        self,
        similarity: float,
    ) -> Dict[str, object]:
        """
        Evaluate similarity against threshold.

        Returns:

            {
                "similarity": 0.721,
                "threshold": 0.70,
                "matched": True
            }
        """

        similarity = float(similarity)

        return {
            "similarity": similarity,
            "threshold": self.threshold,
            "matched": similarity >= self.threshold,
        }