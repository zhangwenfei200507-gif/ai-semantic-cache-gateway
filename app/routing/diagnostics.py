from __future__ import annotations

from app.gateway import get_gateway


def diagnose(
    messages: list[dict],
) -> dict:

    gateway = get_gateway()

    decision = (
        gateway.model_router.route(
            messages
        )
    )

    return decision.to_dict()


def print_diagnosis(
    messages: list[dict],
) -> None:

    data = diagnose(
        messages
    )

    profile = data[
        "request_profile"
    ]

    print()
    print("=" * 80)
    print("AI GATEWAY ROUTER DIAGNOSTICS")
    print("=" * 80)

    print()
    print("[REQUEST]")

    for key in (
        "task",
        "task_confidence",
        "domain",
        "domain_confidence",
        "language",
        "chinese_ratio",
        "complexity",
        "complexity_score",
        "coding_score",
        "reasoning_score",
        "analysis_score",
        "factual_score",
        "creative_score",
        "data_score",
        "estimated_input_tokens",
    ):
        print(
            f"{key}: {profile.get(key)}"
        )

    print()
    print("[SELECTED]")

    print(
        "provider:",
        data["provider"],
    )

    print(
        "model:",
        data["model"],
    )

    print(
        "score:",
        data["score"],
    )

    print(
        "confidence:",
        data["confidence"],
    )

    print(
        "confidence_level:",
        data["confidence_level"],
    )

    print(
        "mode:",
        data["mode"],
    )

    print(
        "reasons:",
        ", ".join(
            data["reasons"]
        ),
    )

    print()
    print("[MODEL COMPARISON]")

    for index, candidate in enumerate(
        data["candidates"],
        start=1,
    ):

        print()

        print(
            f"#{index} "
            f"{candidate['provider']}/"
            f"{candidate['model']}"
        )

        print(
            "  semantic:",
            candidate["semantic_score"],
        )

        print(
            "  task:",
            candidate["task_score"],
        )

        print(
            "  domain:",
            candidate["domain_score"],
        )

        print(
            "  language:",
            candidate["language_score"],
        )

        print(
            "  complexity:",
            candidate["complexity_score"],
        )

        print(
            "  quality:",
            candidate["quality_score"],
        )

        print(
            "  cost_score:",
            candidate["cost_score"],
        )

        print(
            "  latency_score:",
            candidate["latency_score"],
        )

        print(
            "  reliability_score:",
            candidate["reliability_score"],
        )

        print(
            "  final_score:",
            candidate["final_score"],
        )

        print(
            "  estimated_cost:",
            candidate["estimated_cost"],
        )

        print(
            "  reasons:",
            ", ".join(
                candidate["reasons"]
            ),
        )

    print()
    print("[FALLBACK]")

    for index, candidate in enumerate(
        data["fallback_candidates"],
        start=1,
    ):

        print(
            f"{index}. "
            f"{candidate['provider']}/"
            f"{candidate['model']}"
        )

    print()
    print("=" * 80)
    print()


__all__ = [
    "diagnose",
    "print_diagnosis",
]
