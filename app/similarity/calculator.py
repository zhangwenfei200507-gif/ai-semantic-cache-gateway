from __future__ import annotations


def calculate_similarity(
    distance: float,
    threshold: float = 0.75,
) -> dict:
    """
    Redis COSINE distance -> similarity.

    Redis:

        0 = identical
        1 = completely different

    Application:

        1 = identical
        0 = completely different
    """

    distance = float(
        distance
    )

    if not 0.0 <= threshold <= 1.0:

        raise ValueError(
            "threshold must be between 0 and 1"
        )

    similarity = (
        1.0 - distance
    )

    similarity = max(
        0.0,
        min(
            1.0,
            similarity,
        ),
    )

    return {
        "distance": distance,
        "similarity": similarity,
        "threshold": threshold,
        "matched": (
            similarity >= threshold
        ),
    }