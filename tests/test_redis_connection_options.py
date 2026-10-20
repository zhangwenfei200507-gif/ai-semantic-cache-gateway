from __future__ import annotations

import os
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
import redis


class _Search:
    def info(self):
        return {
            "attributes": [
                ["identifier", "embedding"],
                ["identifier", "workspace_id"],
                ["identifier", "cache_scope"],
            ]
        }

    def create_index(self, **_kwargs):
        return True


class _Redis:
    def __init__(self):
        self.search = _Search()

    def ft(self, _name):
        return self.search

    def ping(self):
        return True


def test_cache_repository_disables_tcp_keepalive():
    from app.cache.cache_repository import CacheRepository
    from app.config.settings import settings

    client = _Redis()
    with patch("app.cache.cache_repository.redis.from_url", return_value=client) as factory:
        repository = CacheRepository()

    assert repository.redis is client
    factory.assert_called_once_with(
        settings.redis_url,
        decode_responses=False,
        socket_keepalive=False,
    )
    assert repository.ping() is True


def test_rate_limiter_disables_tcp_keepalive():
    from app.security.rate_limit import GatewayRateLimiter
    from app.config.settings import settings

    client = Mock()
    limiter = GatewayRateLimiter()
    with patch("app.security.rate_limit.redis.from_url", return_value=client) as factory:
        assert limiter._client() is client

    factory.assert_called_once_with(
        settings.redis_url,
        decode_responses=True,
        socket_keepalive=False,
    )


def test_legacy_cache_engine_disables_tcp_keepalive():
    from app.cache.cache_engine import CacheEngine

    client = _Redis()
    with patch("app.cache.cache_engine.redis.Redis.from_url", return_value=client) as factory:
        engine = CacheEngine(redis_url="redis://cache.test:6379/0")

    assert engine.client is client
    factory.assert_called_once_with(
        "redis://cache.test:6379/0",
        decode_responses=False,
        socket_keepalive=False,
    )


@pytest.mark.skipif(
    not os.getenv("STAGE8_REDIS_URL"),
    reason="Set STAGE8_REDIS_URL to run the isolated Redis reconnect test",
)
def test_redis_reconnects_after_idle_connection_is_disconnected():
    """Verify disabling TCP keepalive does not disable redis-py reconnects."""
    client = redis.Redis.from_url(
        os.environ["STAGE8_REDIS_URL"],
        socket_keepalive=False,
    )
    key = f"ascg:stage8:reconnect:{uuid4().hex}"
    try:
        assert client.set(key, b"ok", ex=60)
        for connection in list(client.connection_pool._available_connections):
            connection.disconnect()
        assert client.get(key) == b"ok"
    finally:
        client.delete(key)
        client.close()
