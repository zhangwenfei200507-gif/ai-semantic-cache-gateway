from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostMetrics:

    total_requests: int = 0

    total_tokens: int = 0

    total_cost: float = 0.0


    def record(
        self,
        tokens: int,
        cost: float,
    ) -> None:

        self.total_requests += 1

        self.total_tokens += int(
            tokens
        )

        self.total_cost += float(
            cost
        )



    def snapshot(self) -> dict:

        return {

            "total_requests":
                self.total_requests,

            "total_tokens":
                self.total_tokens,

            "total_cost":
                round(
                    self.total_cost,
                    8,
                ),

        }



cost_metrics = CostMetrics()