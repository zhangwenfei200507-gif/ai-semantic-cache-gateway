from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock


class HistoryDatabase:
    """
    SQLite database manager.

    Stores gateway request history.

    Default:

        data/gateway.db
    """

    def __init__(
        self,
        db_path: str | None = None,
    ) -> None:

        if db_path is None:
            base = Path("data")
            base.mkdir(
                exist_ok=True
            )

            db_path = str(
                base / "gateway.db"
            )

        self.db_path = db_path

        self._lock = Lock()

        self._initialize()



    def _connect(self):

        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )

        conn.row_factory = sqlite3.Row

        return conn



    def _initialize(self):

        with self._lock:

            conn = self._connect()

            try:

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS request_history
                    (

                        id INTEGER PRIMARY KEY AUTOINCREMENT,

                        request_id TEXT UNIQUE,

                        user_id TEXT,

                        provider TEXT,

                        model TEXT,

                        question TEXT,

                        answer TEXT,

                        cache_hit INTEGER DEFAULT 0,

                        cache_type TEXT,

                        similarity REAL,

                        threshold REAL,

                        latency_ms REAL DEFAULT 0,

                        provider_latency_ms REAL DEFAULT 0,

                        prompt_tokens INTEGER DEFAULT 0,

                        completion_tokens INTEGER DEFAULT 0,

                        total_tokens INTEGER DEFAULT 0,

                        cost REAL DEFAULT 0,

                        status TEXT,

                        error TEXT,

                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP

                    )
                    """
                )


                conn.commit()


            finally:

                conn.close()



    def execute(
        self,
        sql: str,
        params: tuple = (),
    ):

        with self._lock:

            conn = self._connect()

            try:

                cursor = conn.execute(
                    sql,
                    params,
                )

                conn.commit()

                return cursor


            finally:

                conn.close()



    def fetch_all(
        self,
        sql: str,
        params: tuple = (),
    ) -> list[dict]:

        with self._lock:

            conn = self._connect()

            try:

                rows = conn.execute(
                    sql,
                    params,
                ).fetchall()


                return [
                    dict(row)
                    for row in rows
                ]


            finally:

                conn.close()



    def fetch_one(
        self,
        sql: str,
        params: tuple = (),
    ):

        with self._lock:

            conn = self._connect()

            try:

                row = conn.execute(
                    sql,
                    params,
                ).fetchone()


                return (
                    dict(row)
                    if row
                    else None
                )


            finally:

                conn.close()



history_database = HistoryDatabase()