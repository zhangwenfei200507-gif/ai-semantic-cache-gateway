from prometheus_client import Counter


CACHE_COUNTER = Counter(
    "cache_total",
    "Cache result",
    [
        "status"
    ]
)