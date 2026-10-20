from __future__ import annotations

from threading import Lock


class LLMMetricCollector:
    """
    Runtime metrics collector for LLM requests.

    Collect:

        - total requests
        - success requests
        - failed requests
        - tokens
        - cost
        - latency
    """


    def __init__(self) -> None:

        self._lock = Lock()

        self.total_requests = 0

        self.success_requests = 0

        self.failed_requests = 0

        self.total_tokens = 0

        self.total_cost = 0.0

        self.total_latency_ms = 0.0



    # =====================================================
    # Record success
    # =====================================================

    def record_success(
        self,
        response,
    ) -> None:


        with self._lock:

            self.total_requests += 1

            self.success_requests += 1


            self.total_tokens += (
                response.total_tokens
            )


            self.total_cost += (
                response.cost
                if isinstance(
                    response.cost,
                    (int, float),
                )
                else 0.0
            )


            self.total_latency_ms += (
                response.latency_ms
                if hasattr(
                    response,
                    "latency_ms",
                )
                else 0.0
            )



    # =====================================================
    # Record failure
    # =====================================================

    def record_failure(
        self,
    ) -> None:


        with self._lock:

            self.total_requests += 1

            self.failed_requests += 1



    # =====================================================
    # Snapshot
    # =====================================================

    def snapshot(
        self,
    ) -> dict:


        with self._lock:


            average_latency = 0.0


            if self.success_requests > 0:

                average_latency = round(

                    self.total_latency_ms
                    /
                    self.success_requests,

                    2,

                )


            return {


                "total_requests":
                    self.total_requests,


                "success_requests":
                    self.success_requests,


                "failed_requests":
                    self.failed_requests,


                "total_tokens":
                    self.total_tokens,


                "total_cost":
                    round(
                        self.total_cost,
                        8,
                    ),


                "average_latency_ms":
                    average_latency,

            }



    # =====================================================
    # Reset (test)
    # =====================================================

    def clear(self):

        with self._lock:

            self.total_requests = 0

            self.success_requests = 0

            self.failed_requests = 0

            self.total_tokens = 0

            self.total_cost = 0.0

            self.total_latency_ms = 0.0



# Global singleton

llm_metrics = LLMMetricCollector()