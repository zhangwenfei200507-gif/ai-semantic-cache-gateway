from __future__ import annotations

import re
from threading import Lock
from typing import Any

from app.config.settings import settings


_pool = None
_pool_lock = Lock()
_QMARK = re.compile(r"\?")


def postgres_configured() -> bool:
    return bool(str(settings.database_url or "").strip())


def _require_driver():
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL is configured but psycopg[binary,pool] is not installed"
        ) from exc
    return ConnectionPool, dict_row


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            ConnectionPool, dict_row = _require_driver()
            _pool = ConnectionPool(
                conninfo=str(settings.database_url),
                min_size=max(1, int(settings.database_pool_min_size)),
                max_size=max(1, int(settings.database_pool_max_size)),
                timeout=float(settings.database_connect_timeout),
                kwargs={
                    "connect_timeout": int(settings.database_connect_timeout),
                    "row_factory": dict_row,
                },
            )
    return _pool


def direct_connection(database_url: str | None = None):
    """Open a migration/diagnostic connection outside the application pool."""
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL is configured but psycopg[binary,pool] is not installed"
        ) from exc
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL")
    return psycopg.connect(
        str(url),
        connect_timeout=int(settings.database_connect_timeout),
        row_factory=dict_row,
    )


def _translate(query: str) -> str:
    return _QMARK.sub("%s", query)


class _PooledConnection:
    def __init__(self) -> None:
        self._lease = None
        self._connection = None

    def __enter__(self):
        self._lease = _get_pool().connection()
        self._connection = self._lease.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._lease.__exit__(exc_type, exc_value, traceback)

    def execute(self, query: str, params: Any = None):
        return self._connection.execute(_translate(query), params)

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def get_postgres_connection() -> _PooledConnection:
    if not postgres_configured():
        raise RuntimeError("DATABASE_URL is not configured")
    return _PooledConnection()


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


__all__ = [
    "close_pool",
    "direct_connection",
    "get_postgres_connection",
    "postgres_configured",
]

