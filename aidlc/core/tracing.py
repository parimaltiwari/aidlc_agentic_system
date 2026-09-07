"""JSONL run tracing."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path


class Tracer:
    def __init__(self, run_id: str, root: str | None = None) -> None:
        self.run_id = run_id
        self.path = Path(root or os.getenv("AIDLC_RUNS_DIR", "./runs")) / run_id / "trace.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self, agent: str, phase: str, duration: float, ok: bool, error: str | None = None
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
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def span(self):
        return time.perf_counter()
