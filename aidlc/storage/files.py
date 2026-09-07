"""File-backed AIDLC storage implementations."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _root() -> Path:
    return Path(os.getenv("AIDLC_RUNS_DIR", "./runs"))


class ArtifactStore:
    def __init__(self, run_id: str, root: str | None = None) -> None:
        self.root = Path(root or _root()) / run_id / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, value: Any) -> str:
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        versions = list(self.root.glob(f"{name}.v*.json"))
        version = max([int(p.stem.split(".v")[-1]) for p in versions] or [0]) + 1
        destination = self.root / f"{name}.v{version}.json"
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (self.root / f"{name}.latest").write_text(destination.name, encoding="utf-8")
        return destination.name

    def list(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("*.v*.json"))

    def read(self, name: str) -> Any:
        pointer = self.root / f"{name}.latest"
        target = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else name
        return json.loads((self.root / target).read_text(encoding="utf-8"))

    def latest_all(self) -> dict[str, Any]:
        result = {}
        for pointer in self.root.glob("*.latest"):
            result[pointer.stem] = self.read(pointer.stem)
        return result


class Tracer:
    def __init__(self, run_id: str, root: str | None = None) -> None:
        self.run_id = run_id
        self.path = Path(root or _root()) / run_id / "trace.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

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
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "phase": phase,
            "agent": agent,
            "duration_ms": round(duration * 1000, 2),
            "ok": ok,
            "error": error,
        }
        if model is not None:
            entry["model"] = model
        if work_item_id is not None:
            entry["work_item_id"] = work_item_id
        entry["attempt"] = attempt
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def span(self):
        return time.perf_counter()


class FileRunRepository:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or _root())

    def _run_root(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _append(self, run_id: str, filename: str, value: dict) -> None:
        with (self._run_root(run_id) / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

    def upsert_run(
        self,
        run_id: str,
        intent: str,
        context: dict,
        status: str,
        phase: str,
        requested_by: str,
    ) -> None:
        path = self._run_root(run_id) / "run.json"
        current = json.loads(path.read_text()) if path.exists() else {}
        current.update(
            {
                "run_id": run_id,
                "intent": intent,
                "context": context,
                "status": status,
                "phase": phase,
                "requested_by": requested_by,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        current.setdefault("created_at", datetime.now(UTC).isoformat())
        path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")

    def update_status(self, run_id: str, status: str, phase: str) -> None:
        current = self.get_run(run_id) or {"run_id": run_id}
        self.upsert_run(
            run_id,
            current.get("intent", ""),
            current.get("context", {}),
            status,
            phase,
            current.get("requested_by", "system"),
        )

    def add_scorecard(self, run_id: str, phase: str, attempt: int, scorecard_dict: dict) -> None:
        self._append(
            run_id,
            "scorecards.jsonl",
            {"phase": phase, "attempt": attempt, "scorecard": scorecard_dict},
        )

    def add_gate_decision(
        self,
        run_id: str,
        phase: str,
        attempt: int,
        decision_dict: dict,
        approval_by: str | None = None,
    ) -> None:
        self._append(
            run_id,
            "gates.jsonl",
            {
                "phase": phase,
                "attempt": attempt,
                "decision": decision_dict,
                "approval_by": approval_by,
            },
        )

    def add_change_request(self, run_id: str, cr_dict: dict) -> None:
        self._append(run_id, "change_requests.jsonl", cr_dict)

    def add_event(self, run_id: str, level: str, message: str) -> None:
        self._append(
            run_id,
            "events.jsonl",
            {"ts": datetime.now(UTC).isoformat(), "level": level, "message": message},
        )

    def get_run(self, run_id: str) -> dict | None:
        path = self._run_root(run_id) / "run.json"
        if not path.exists():
            return None
        result = json.loads(path.read_text())
        change_path = self._run_root(run_id) / "change_requests.jsonl"
        if change_path.exists():
            result["change_requests"] = [
                json.loads(line) for line in change_path.read_text().splitlines() if line
            ]
        return result

    def latest_artifacts(self, run_id: str) -> dict[str, Any]:
        return ArtifactStore(run_id, root=str(self.root)).latest_all()
