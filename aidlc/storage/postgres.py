"""Postgres-backed AIDLC history and artifact stores."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from threading import Lock
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from aidlc.storage.migrations import apply

_pool_lock = Lock()
_pools: dict[str, ConnectionPool] = {}
_schema_urls: set[str] = set()


def _pool() -> ConnectionPool:
    database_url = os.getenv("AIDLC_DATABASE_URL")
    if not database_url:
        raise RuntimeError("AIDLC_DATABASE_URL is required for Postgres storage")
    with _pool_lock:
        pool = _pools.get(database_url)
        if pool is None:
            pool = ConnectionPool(database_url, open=False)
            _pools[database_url] = pool
        if pool.closed:
            pool.open(wait=True)
        return pool


def _ensure_schema() -> None:
    database_url = os.getenv("AIDLC_DATABASE_URL")
    if not database_url:
        raise RuntimeError("AIDLC_DATABASE_URL is required for Postgres storage")
    pool = _pool()
    with _pool_lock:
        if database_url in _schema_urls:
            return
        with pool.connection() as connection:
            apply(connection)
        _schema_urls.add(database_url)


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ensure_run(connection, run_id: str) -> None:
    connection.execute(
        """
        INSERT INTO runs (id, project_id, intent, context, status, phase, requested_by)
        VALUES (%s, 'default', '', '{}'::jsonb, 'running', 'unknown', 'system')
        ON CONFLICT (id) DO NOTHING
        """,
        (run_id,),
    )


class PostgresArtifactStore:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        _ensure_schema()

    def save(self, name: str, value: Any) -> str:
        payload = _json(value)
        content_hash = _hash(payload)
        schema = type(value).__name__ if hasattr(value, "model_dump") else "dict"
        with _pool().connection() as connection:
            _ensure_run(connection, self.run_id)
            latest = connection.execute(
                """
                SELECT version, content_hash FROM artifact_versions
                WHERE run_id = %s AND key = %s
                ORDER BY version DESC LIMIT 1
                """,
                (self.run_id, name),
            ).fetchone()
            if latest and latest[1] == content_hash:
                return f"{name}.v{latest[0]}"
            version = (latest[0] if latest else 0) + 1
            connection.execute(
                """
                INSERT INTO artifact_versions
                (run_id, key, version, schema, phase, agent, attempt, body, blob_uri, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, %s)
                """,
                (
                    self.run_id,
                    name,
                    version,
                    schema,
                    os.getenv("AIDLC_PHASE", "unknown"),
                    os.getenv("AIDLC_AGENT", "system"),
                    int(os.getenv("AIDLC_ATTEMPT", "1")),
                    Jsonb(payload),
                    content_hash,
                ),
            )
        return f"{name}.v{version}"

    def list(self) -> list[str]:
        with _pool().connection() as connection:
            rows = connection.execute(
                "SELECT key, version FROM artifact_versions WHERE run_id = %s "
                "ORDER BY key, version",
                (self.run_id,),
            ).fetchall()
        return [f"{row[0]}.v{row[1]}" for row in rows]

    def read(self, name: str) -> Any:
        key, _, version = name.partition(".v")
        with _pool().connection() as connection:
            if version:
                row = connection.execute(
                    """
                    SELECT body FROM artifact_versions
                    WHERE run_id = %s AND key = %s AND version = %s
                    """,
                    (self.run_id, key, int(version)),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT body FROM artifact_versions
                    WHERE run_id = %s AND key = %s
                    ORDER BY version DESC LIMIT 1
                    """,
                    (self.run_id, key),
                ).fetchone()
        if row is None:
            raise FileNotFoundError(name)
        return row[0]

    def latest_all(self) -> dict[str, Any]:
        with _pool().connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (key) key, body
                FROM artifact_versions
                WHERE run_id = %s
                ORDER BY key, version DESC
                """,
                (self.run_id,),
            ).fetchall()
        return {row[0]: row[1] for row in rows}


class PostgresTracer:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        _ensure_schema()

    def record(
        self,
        agent: str,
        phase: str,
        duration: float,
        ok: bool,
        error: str | None = None,
        *,
        model: str | None = None,
        work_item_id: str | None = None,
        attempt: int = 1,
    ) -> None:
        with _pool().connection() as connection:
            _ensure_run(connection, self.run_id)
            connection.execute(
                """
                INSERT INTO agent_invocations
                (run_id, phase, agent, work_item_id, attempt, worker_id,
                 temporal_activity_id, model, input_keys, output_key,
                 started_at, duration_ms, ok, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s)
                """,
                (
                    self.run_id,
                    phase,
                    agent,
                    work_item_id,
                    attempt,
                    f"{socket.gethostname()}:{os.getpid()}",
                    os.getenv("TEMPORAL_ACTIVITY_ID"),
                    model,
                    os.getenv("AIDLC_INPUT_KEYS", "").split(",")
                    if os.getenv("AIDLC_INPUT_KEYS")
                    else [],
                    os.getenv("AIDLC_OUTPUT_KEY"),
                    datetime.now(UTC) - timedelta(seconds=duration),
                    round(duration * 1000),
                    ok,
                    error,
                ),
            )

    def span(self):
        return time.perf_counter()


class PostgresRunRepository:
    def __init__(self) -> None:
        _ensure_schema()

    def upsert_run(
        self,
        run_id: str,
        intent: str,
        context: dict,
        status: str,
        phase: str,
        requested_by: str,
    ) -> None:
        clean_context = {key: value for key, value in context.items() if not key.startswith("_")}
        with _pool().connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, project_id, intent, context, status, phase, requested_by)
                VALUES (%s, 'default', %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  intent = EXCLUDED.intent, context = EXCLUDED.context,
                  status = EXCLUDED.status, phase = EXCLUDED.phase,
                  requested_by = EXCLUDED.requested_by, updated_at = now()
                """,
                (run_id, intent, Jsonb(clean_context), status, phase, requested_by),
            )

    def update_status(self, run_id: str, status: str, phase: str) -> None:
        with _pool().connection() as connection:
            connection.execute(
                "UPDATE runs SET status = %s, phase = %s, updated_at = now() WHERE id = %s",
                (status, phase, run_id),
            )

    def add_scorecard(self, run_id: str, phase: str, attempt: int, scorecard_dict: dict) -> None:
        with _pool().connection() as connection:
            connection.execute(
                """
                INSERT INTO scorecards
                (run_id, phase, attempt, agent, scores, overall, passed, feedback)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    phase,
                    attempt,
                    scorecard_dict.get("agent", "evaluator"),
                    Jsonb(scorecard_dict.get("scores", {})),
                    scorecard_dict.get("overall", 0.0),
                    scorecard_dict.get("passed", False),
                    scorecard_dict.get("feedback", []),
                ),
            )

    def add_gate_decision(
        self,
        run_id: str,
        phase: str,
        attempt: int,
        decision_dict: dict,
        approval_by: str | None = None,
    ) -> None:
        approved_by = approval_by or decision_dict.get("approved_by")
        with _pool().connection() as connection:
            connection.execute(
                """
                INSERT INTO gate_decisions
                (run_id, phase, attempt, decision, reason, approved, approved_by, approved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END)
                """,
                (
                    run_id,
                    phase,
                    attempt,
                    decision_dict.get("decision", "review"),
                    decision_dict.get("reason", ""),
                    decision_dict.get("approved"),
                    approved_by,
                    approved_by is not None,
                ),
            )

    def add_change_request(self, run_id: str, cr_dict: dict) -> None:
        with _pool().connection() as connection:
            connection.execute(
                """
                INSERT INTO change_requests
                (run_id, cr_id, source_phase, target_phase, reason, details)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    cr_dict["id"],
                    cr_dict["source_phase"],
                    cr_dict["target_phase"],
                    cr_dict["reason"],
                    cr_dict.get("details", []),
                ),
            )

    def add_event(self, run_id: str, level: str, message: str) -> None:
        with _pool().connection() as connection:
            connection.execute(
                "INSERT INTO run_events (run_id, level, message) VALUES (%s, %s, %s)",
                (run_id, level, message),
            )

    def get_run(self, run_id: str) -> dict | None:
        with _pool().connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                row = cursor.execute(
                    """
                    SELECT id, project_id, intent, context, status, phase, requested_by,
                           parent_run_id, created_at, updated_at
                    FROM runs WHERE id = %s
                    """,
                    (run_id,),
                ).fetchone()
            if row:
                cr_rows = connection.execute(
                    """
                    SELECT cr_id, source_phase, target_phase, reason, details
                    FROM change_requests WHERE run_id = %s ORDER BY id
                    """,
                    (run_id,),
                ).fetchall()
                row["change_requests"] = [
                    {
                        "id": cr[0],
                        "source_phase": cr[1],
                        "target_phase": cr[2],
                        "reason": cr[3],
                        "details": cr[4],
                    }
                    for cr in cr_rows
                ]
        return dict(row) if row else None

    def latest_artifacts(self, run_id: str) -> dict[str, Any]:
        return PostgresArtifactStore(run_id).latest_all()
