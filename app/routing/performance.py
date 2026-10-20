from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class PerformanceSample:
    latency_ms: float
    success: bool


class PerformanceTracker:
    """
    Process-local adaptive operational telemetry.

    Reliability and latency are learned from actual provider
    requests when the gateway records them.

    Until data exists, conservative neutral priors are used.
    """

    DEFAULT_LATENCY_MS = 900.0
    DEFAULT_RELIABILITY = 0.97

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._samples: dict[
            tuple[str, str],
            list[PerformanceSample],
        ] = {}

    def record(
        self,
        provider: str,
        model: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        key = (provider, model)

        sample = PerformanceSample(
            latency_ms=max(
                0.1,
                float(latency_ms),
            ),
            success=bool(success),
        )

        with self._lock:
            bucket = self._samples.setdefault(
                key,
                [],
            )

            bucket.append(sample)

            # Keep recent history bounded.
            if len(bucket) > 200:
                del bucket[:-200]

    def observe(
        self,
        provider: str,
        model: str,
    ):
        start = time.perf_counter()

        tracker = self

        class _Observation:
            def __enter__(self_inner):
                return self_inner

            def __exit__(
                self_inner,
                exc_type,
                exc,
                tb,
            ):
                latency = (
                    time.perf_counter()
                    -
                    start
                ) * 1000.0

                tracker.record(
                    provider,
                    model,
                    latency,
                    exc_type is None,
                )

        return _Observation()

    def _history(
        self,
        provider: str,
        model: str,
    ) -> list[PerformanceSample]:
        with self._lock:
            return list(
                self._samples.get(
                    (provider, model),
                    [],
                )
            )

    def latency_ms(
        self,
        provider: str,
        model: str,
    ) -> float:
        history = self._history(
            provider,
            model,
        )

        if not history:
            return self.DEFAULT_LATENCY_MS

        # EWMA-style weighting: recent measurements matter more.
        weighted = 0.0
        weight_sum = 0.0

        decay = 0.94

        for index, sample in enumerate(
            reversed(history)
        ):
            weight = math.pow(
                decay,
                index,
            )

            weighted += (
                sample.latency_ms
                *
                weight
            )

            weight_sum += weight

        if weight_sum <= 0.0:
            return self.DEFAULT_LATENCY_MS

        return weighted / weight_sum

    def reliability(
        self,
        provider: str,
        model: str,
    ) -> float:
        history = self._history(
            provider,
            model,
        )

        if not history:
            return self.DEFAULT_RELIABILITY

        successes = sum(
            1
            for sample in history
            if sample.success
        )

        # Bayesian smoothing prevents one early failure
        # from destroying a model's operational score.
        alpha = 19.0
        beta = 1.0

        return (
            alpha + successes
        ) / (
            alpha
            +
            beta
            +
            len(history)
        )

    def snapshot(self) -> dict:
        with self._lock:
            result = {}

            for (
                provider,
                model,
            ), _ in self._samples.items():
                result[
                    f"{provider}/{model}"
                ] = {
                    "latency_ms": self.latency_ms(
                        provider,
                        model,
                    ),
                    "reliability": self.reliability(
                        provider,
                        model,
                    ),
                    "samples": len(
                        self._samples[
                            (provider, model)
                        ]
                    ),
                }

            return result


performance_tracker = PerformanceTracker()


__all__ = [
    "PerformanceTracker",
    "PerformanceSample",
    "performance_tracker",
]
