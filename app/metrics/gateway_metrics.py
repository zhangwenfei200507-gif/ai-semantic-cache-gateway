from __future__ import annotations

from prometheus_client import Counter, Histogram


# Keep these metrics label-free for a stable internal contract. This avoids
# the "metric is missing label values" failure that occurred when callers
# used .inc()/.observe() on labelled metrics.
GATEWAY_REQUEST_TOTAL = Counter(
    "gateway_requests_total",
    "Total gateway requests",
)

GATEWAY_ERROR_TOTAL = Counter(
    "gateway_errors_total",
    "Total gateway errors",
)

CACHE_HIT_TOTAL = Counter(
    "gateway_cache_hits_total",
    "Total cache hits",
)

CACHE_MISS_TOTAL = Counter(
    "gateway_cache_misses_total",
    "Total cache misses",
)

CACHE_EXACT_HIT_TOTAL = Counter(
    "gateway_cache_exact_hits_total",
    "Total exact cache hits",
)

CACHE_SEMANTIC_HIT_TOTAL = Counter(
    "gateway_cache_semantic_hits_total",
    "Total semantic cache hits",
)

PROVIDER_REQUEST_TOTAL = Counter(
    "gateway_provider_requests_total",
    "Total upstream provider requests",
)

PROVIDER_ERROR_TOTAL = Counter(
    "gateway_provider_errors_total",
    "Total upstream provider errors",
)

PROVIDER_LATENCY_SECONDS = Histogram(
    "gateway_provider_latency_seconds",
    "Upstream provider latency in seconds",
)

REQUEST_LATENCY_SECONDS = Histogram(
    "gateway_request_latency_seconds",
    "End-to-end gateway latency in seconds",
)

# Backward-compatible aliases used by some existing code.
REQUEST_TOTAL = GATEWAY_REQUEST_TOTAL
ERROR_TOTAL = GATEWAY_ERROR_TOTAL
