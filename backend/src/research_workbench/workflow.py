import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime

from .models import AuditEvent, ResearchRun


class WorkflowConflictError(RuntimeError):
    pass


class SQLiteWorkflowStore:
    """Durable run state and append-only audit events for the local deployment."""

    def __init__(self, path: str) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS research_runs (
                  id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL,
                  revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  state TEXT NOT NULL,
                  detail_hash TEXT NOT NULL,
                  trace_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(run_id) REFERENCES research_runs(id)
                );
                """
            )

    def create(self, run: ResearchRun, actor: str, detail: dict[str, object]) -> ResearchRun:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO research_runs(id, payload_json, revision) VALUES (?, ?, 0)",
                (run.id, run.model_dump_json()),
            )
            self._append(run, "run.created", actor, detail)
        return run

    def get(self, run_id: str) -> ResearchRun:
        row = self._connection.execute(
            "SELECT payload_json FROM research_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return ResearchRun.model_validate_json(row["payload_json"])

    def transition(
        self,
        run_id: str,
        expected: set[str],
        updated: ResearchRun,
        event_type: str,
        actor: str,
        detail: dict[str, object],
    ) -> ResearchRun:
        with self._lock, self._connection:
            current = self.get(run_id)
            if current.state not in expected:
                raise WorkflowConflictError(
                    f"run {run_id} is {current.state}; expected one of {sorted(expected)}"
                )
            cursor = self._connection.execute(
                "UPDATE research_runs SET payload_json = ?, revision = revision + 1 WHERE id = ?",
                (updated.model_dump_json(), run_id),
            )
            if cursor.rowcount != 1:
                raise WorkflowConflictError("run changed during transition")
            self._append(updated, event_type, actor, detail)
        return updated

    def _append(
        self, run: ResearchRun, event_type: str, actor: str, detail: dict[str, object]
    ) -> None:
        detail_json = json.dumps(detail, sort_keys=True, separators=(",", ":"))
        self._connection.execute(
            """
            INSERT INTO audit_events(run_id, event_type, actor, state, detail_hash, trace_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                event_type,
                actor,
                run.state,
                hashlib.sha256(detail_json.encode()).hexdigest(),
                run.trace_id,
                datetime.now(UTC).isoformat(),
            ),
        )

    def events(self, run_id: str, after_id: int = 0) -> list[AuditEvent]:
        rows = self._connection.execute(
            "SELECT * FROM audit_events WHERE run_id = ? AND id > ? ORDER BY id",
            (run_id, after_id),
        ).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                run_id=row["run_id"],
                event_type=row["event_type"],
                actor=row["actor"],
                state=row["state"],
                detail_hash=row["detail_hash"],
                trace_id=row["trace_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
