from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.cost.cost_calculator import cost_calculator
from app.db.postgres import get_postgres_connection, postgres_configured


class HistoryRepository:
    """
    SQLite based gateway request history storage.

    Responsible for:
    - saving requests
    - listing requests
    - searching requests
    - request detail lookup
    - dashboard statistics
    """

    def __init__(
        self,
        db_path: str = "data/gateway.db",
    ) -> None:

        self.db_path = Path(db_path)

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.lock = threading.Lock()

        self._initialize()


    # ============================================================
    # Database
    # ============================================================

    def _connect(self):

        connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )

        connection.row_factory = sqlite3.Row

        return connection

    @staticmethod
    def _with_cost(record: dict[str, Any]) -> dict[str, Any]:
        if not record.get("cost") and record.get("total_tokens"):
            priced = cost_calculator.calculate(
                str(record.get("model") or ""),
                {
                    "prompt_tokens": record.get("prompt_tokens", 0),
                    "completion_tokens": record.get("completion_tokens", 0),
                },
            )
            if priced["total_cost"] > 0:
                record["cost"] = priced["total_cost"]
        return record



    def _initialize(self):

        with self.lock:

            conn = self._connect()

            cursor = conn.cursor()


            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_history
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


                    prompt_tokens INTEGER DEFAULT 0,

                    completion_tokens INTEGER DEFAULT 0,

                    total_tokens INTEGER DEFAULT 0,


                    cost REAL DEFAULT 0,

                    saved_cost REAL DEFAULT 0,


                    latency_ms REAL DEFAULT 0,

                    provider_latency_ms REAL DEFAULT 0,


                    status TEXT DEFAULT 'success',

                    error TEXT,


                    created_at TEXT

                )
                """
            )


            conn.commit()

            conn.close()



    # ============================================================
    # Insert
    # ============================================================

    def save(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:


        request_id = (
            data.get("request_id")
            or
            f"req_{uuid.uuid4().hex[:12]}"
        )


        created_at = (
            data.get("created_at")
            or
            datetime.utcnow()
            .isoformat()
        )


        record = {

            "request_id":
                request_id,

            "user_id":
                data.get("user_id"),


            "provider":
                data.get("provider"),


            "model":
                data.get("model"),


            "question":
                data.get("question",""),


            "answer":
                data.get("answer",""),


            "cache_hit":
                1 if data.get("cache_hit")
                else 0,


            "cache_type":
                data.get("cache_type"),


            "similarity":
                data.get("similarity"),


            "threshold":
                data.get("threshold"),


            "prompt_tokens":
                data.get("prompt_tokens",0),


            "completion_tokens":
                data.get(
                    "completion_tokens",
                    0,
                ),


            "total_tokens":
                data.get(
                    "total_tokens",
                    0,
                ),


            "cost":
                data.get("cost",0),


            "saved_cost":
                data.get(
                    "saved_cost",
                    0,
                ),


            "latency_ms":
                data.get(
                    "latency_ms",
                    0,
                ),


            "provider_latency_ms":
                data.get(
                    "provider_latency_ms",
                    0,
                ),


            "status":
                data.get(
                    "status",
                    "success",
                ),


            "error":
                data.get("error"),


            "created_at":
                created_at,

        }



        with self.lock:

            conn = self._connect()

            cursor = conn.cursor()


            cursor.execute(
                """
                INSERT INTO gateway_history
                (
                    request_id,
                    user_id,
                    provider,
                    model,
                    question,
                    answer,
                    cache_hit,
                    cache_type,
                    similarity,
                    threshold,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost,
                    saved_cost,
                    latency_ms,
                    provider_latency_ms,
                    status,
                    error,
                    created_at
                )

                VALUES
                (
                    :request_id,
                    :user_id,
                    :provider,
                    :model,
                    :question,
                    :answer,
                    :cache_hit,
                    :cache_type,
                    :similarity,
                    :threshold,
                    :prompt_tokens,
                    :completion_tokens,
                    :total_tokens,
                    :cost,
                    :saved_cost,
                    :latency_ms,
                    :provider_latency_ms,
                    :status,
                    :error,
                    :created_at
                )

                """,
                record,
            )


            conn.commit()

            conn.close()


        return record



    # ============================================================
    # Query
    # ============================================================

    def list(
        self,
        limit: int = 50,
        user_id: str | None = None,
        workspace_id: int | str | None = None,
    ) -> list[dict[str, Any]]:


        with self.lock:

            conn = self._connect()

            cursor = conn.cursor()


            cursor.execute(
                """
                SELECT *
                FROM gateway_history
                WHERE (? IS NULL OR user_id = ?)
                ORDER BY id DESC

                LIMIT ?
                """,
                (
                    user_id,
                    user_id,
                    limit,
                ),
            )


            rows = cursor.fetchall()

            conn.close()


        return [
            self._with_cost(dict(row))
            for row in rows
        ]



    def search(
        self,
        keyword: str | None = None,
        cache_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        user_id: str | None = None,
        workspace_id: int | str | None = None,
    ) -> list[dict[str,Any]]:


        sql = """
        SELECT *
        FROM gateway_history
        WHERE 1=1
        """

        params = []

        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(str(user_id))


        if keyword:

            sql += """
            AND
            (
                question LIKE ?
                OR answer LIKE ?
                OR request_id LIKE ?
                OR user_id LIKE ?
            )
            """

            value = f"%{keyword}%"

            params.extend(
                [
                    value,
                    value,
                    value,
                    value,
                ]
            )



        if cache_type:

            sql += """
            AND cache_type = ?
            """

            params.append(
                cache_type
            )



        if status:

            sql += """
            AND status = ?
            """

            params.append(
                status
            )



        sql += """
        ORDER BY id DESC
        LIMIT ?
        """


        params.append(
            limit
        )



        with self.lock:

            conn = self._connect()

            cursor = conn.cursor()


            cursor.execute(
                sql,
                params,
            )


            rows = cursor.fetchall()

            conn.close()



        return [
            self._with_cost(dict(row))
            for row in rows
        ]



    def get(
        self,
        request_id: str,
        user_id: str | None = None,
        workspace_id: int | str | None = None,
    ) -> dict[str,Any] | None:


        with self.lock:

            conn = self._connect()

            cursor = conn.cursor()


            cursor.execute(
                """
                SELECT *
                FROM gateway_history
                WHERE request_id = ?
                AND (? IS NULL OR user_id = ?)
                """,
                (
                    request_id,
                    user_id,
                    user_id,
                ),
            )


            row = cursor.fetchone()

            conn.close()



        if row is None:
            return None


        return self._with_cost(dict(row))



    # ============================================================
    # Statistics
    # ============================================================

    def count(self):

        with self.lock:

            conn = self._connect()

            cursor = conn.cursor()


            cursor.execute(
                """
                SELECT COUNT(*)
                FROM gateway_history
                """
            )


            result = cursor.fetchone()[0]

            conn.close()


        return result



    def clear(self, user_id: str | None = None, workspace_id: int | str | None = None) -> None:
        """Remove all persisted gateway history records."""
        with self.lock:
            conn = self._connect()
            try:
                if user_id is None:
                    conn.execute("DELETE FROM gateway_history")
                else:
                    conn.execute("DELETE FROM gateway_history WHERE user_id = ?", (str(user_id),))
                conn.commit()
            finally:
                conn.close()


    def stats(self, user_id: str | None = None, workspace_id: int | str | None = None):

        records = self.list(100000, user_id=user_id)


        total = len(records)


        if total == 0:

            return {

                "total":0,

                "hit_rate":0,

                "cost":0,

                "saved_cost":0,

                "tokens":0,

            }



        hits = sum(
            1
            for x in records
            if x["cache_hit"]
        )


        return {

            "total":
                total,

            "hit_rate":
                round(
                    hits / total * 100,
                    2,
                ),

            "cost":
                sum(
                    x["cost"]
                    or 0
                    for x in records
                ),

            "saved_cost":
                sum(
                    x["saved_cost"]
                    or 0
                    for x in records
                ),

            "tokens":
                sum(
                    x["total_tokens"]
                    or 0
                    for x in records
                ),

        }



class PostgresHistoryRepository:
    """PostgreSQL implementation with the same public API as SQLite history."""

    def __init__(self) -> None:
        from app.db.schema import require_schema

        require_schema()

    @staticmethod
    def _with_cost(record: dict[str, Any]) -> dict[str, Any]:
        if not record.get("cost") and record.get("total_tokens"):
            priced = cost_calculator.calculate(
                str(record.get("model") or ""),
                {
                    "prompt_tokens": record.get("prompt_tokens", 0),
                    "completion_tokens": record.get("completion_tokens", 0),
                },
            )
            if priced["total_cost"] > 0:
                record["cost"] = priced["total_cost"]
        return record

    @staticmethod
    def _workspace_for_user(conn, user_id: str | None) -> int | None:
        if user_id is None or not str(user_id).isdigit():
            return None
        row = conn.execute(
            "SELECT id FROM workspaces WHERE owner_user_id = %s",
            (int(user_id),),
        ).fetchone()
        return int(row["id"]) if row else None

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        request_id = data.get("request_id") or f"req_{uuid.uuid4().hex[:12]}"
        created_at = data.get("created_at") or datetime.utcnow().isoformat()
        user_id = data.get("user_id")
        record = {
            "request_id": request_id,
            "user_id": user_id,
            "workspace_id": data.get("workspace_id"),
            "legacy_user_id": data.get("legacy_user_id"),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "question": data.get("question", ""),
            "answer": data.get("answer", ""),
            "cache_hit": bool(data.get("cache_hit")),
            "cache_type": data.get("cache_type"),
            "similarity": data.get("similarity"),
            "threshold": data.get("threshold"),
            "prompt_tokens": data.get("prompt_tokens", 0),
            "completion_tokens": data.get("completion_tokens", 0),
            "total_tokens": data.get("total_tokens", 0),
            "cost": data.get("cost", 0),
            "saved_cost": data.get("saved_cost", 0),
            "latency_ms": data.get("latency_ms", 0),
            "provider_latency_ms": data.get("provider_latency_ms", 0),
            "status": data.get("status", "success"),
            "error": data.get("error"),
            "created_at": created_at,
        }
        with get_postgres_connection() as conn:
            if record["workspace_id"] is None:
                record["workspace_id"] = self._workspace_for_user(conn, user_id)
            conn.execute(
                """
                INSERT INTO gateway_history
                (request_id, user_id, workspace_id, legacy_user_id, provider, model,
                 question, answer, cache_hit, cache_type, similarity, threshold,
                 prompt_tokens, completion_tokens, total_tokens, cost, saved_cost,
                 latency_ms, provider_latency_ms, status, error, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                tuple(record.values()),
            )
        return record

    def list(
        self,
        limit: int = 50,
        user_id: str | None = None,
        workspace_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        with get_postgres_connection() as conn:
            if workspace_id is not None:
                rows = conn.execute(
                    "SELECT * FROM gateway_history WHERE workspace_id = %s ORDER BY id DESC LIMIT %s",
                    (int(workspace_id), limit),
                ).fetchall()
            elif user_id is None:
                rows = conn.execute(
                    "SELECT * FROM gateway_history ORDER BY id DESC LIMIT %s",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gateway_history WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                    (str(user_id), limit),
                ).fetchall()
        return [self._with_cost(dict(row)) for row in rows]

    def search(
        self,
        keyword: str | None = None,
        cache_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        user_id: str | None = None,
        workspace_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM gateway_history WHERE 1=1"
        params: list[Any] = []
        if workspace_id is not None:
            sql += " AND workspace_id = %s"
            params.append(int(workspace_id))
        elif user_id is not None:
            sql += " AND user_id = %s"
            params.append(str(user_id))
        if keyword:
            sql += " AND (question LIKE %s OR answer LIKE %s OR request_id LIKE %s OR user_id LIKE %s)"
            value = f"%{keyword}%"
            params.extend([value, value, value, value])
        if cache_type:
            sql += " AND cache_type = %s"
            params.append(cache_type)
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with get_postgres_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._with_cost(dict(row)) for row in rows]

    def get(
        self,
        request_id: str,
        user_id: str | None = None,
        workspace_id: int | str | None = None,
    ) -> dict[str, Any] | None:
        with get_postgres_connection() as conn:
            if workspace_id is not None:
                row = conn.execute(
                    "SELECT * FROM gateway_history WHERE request_id = %s AND workspace_id = %s",
                    (request_id, int(workspace_id)),
                ).fetchone()
            elif user_id is None:
                row = conn.execute(
                    "SELECT * FROM gateway_history WHERE request_id = %s",
                    (request_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM gateway_history WHERE request_id = %s AND user_id = %s",
                    (request_id, str(user_id)),
                ).fetchone()
        return self._with_cost(dict(row)) if row else None

    def count(self) -> int:
        with get_postgres_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM gateway_history").fetchone()
        return int(row["count"])

    def clear(self, user_id: str | None = None, workspace_id: int | str | None = None) -> None:
        with get_postgres_connection() as conn:
            if workspace_id is not None:
                conn.execute("DELETE FROM gateway_history WHERE workspace_id = %s", (int(workspace_id),))
            elif user_id is None:
                conn.execute("DELETE FROM gateway_history")
            else:
                conn.execute("DELETE FROM gateway_history WHERE user_id = %s", (str(user_id),))

    def stats(self, user_id: str | None = None, workspace_id: int | str | None = None):
        records = self.list(100000, user_id=user_id, workspace_id=workspace_id)
        total = len(records)
        if total == 0:
            return {"total": 0, "hit_rate": 0, "cost": 0, "saved_cost": 0, "tokens": 0}
        hits = sum(1 for item in records if item["cache_hit"])
        return {
            "total": total,
            "hit_rate": round(hits / total * 100, 2),
            "cost": sum(item["cost"] or 0 for item in records),
            "saved_cost": sum(item["saved_cost"] or 0 for item in records),
            "tokens": sum(item["total_tokens"] or 0 for item in records),
        }


history_repository = PostgresHistoryRepository() if postgres_configured() else HistoryRepository()
