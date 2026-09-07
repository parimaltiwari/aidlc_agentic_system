"""Versioned file artifact store."""

import json
import os
from pathlib import Path
from typing import Any


class ArtifactStore:
    def __init__(self, run_id: str, root: str | None = None) -> None:
        self.root = Path(root or os.getenv("AIDLC_RUNS_DIR", "./runs")) / run_id / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, value: Any) -> Path:
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        versions = list(self.root.glob(f"{name}.v*.json"))
        version = max([int(p.stem.split(".v")[-1]) for p in versions] or [0]) + 1
        destination = self.root / f"{name}.v{version}.json"
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (self.root / f"{name}.latest").write_text(destination.name, encoding="utf-8")
        return destination

    def list(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("*.v*.json"))

    def read(self, name: str) -> Any:
        pointer = self.root / f"{name}.latest"
        target = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else name
        return json.loads((self.root / target).read_text(encoding="utf-8"))
