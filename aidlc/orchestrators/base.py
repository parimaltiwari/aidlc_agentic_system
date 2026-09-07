"""Helpers for phase graph nodes."""

from pathlib import Path
from typing import Any

from aidlc.core.agent import BaseAgent
from aidlc.core.state import AidlcState
from aidlc.core.store import ArtifactStore


def agent_node(agent: BaseAgent):
    return agent.as_node()


def assemble(state: AidlcState, name: str, value: Any) -> dict:
    ArtifactStore(state.get("run_id", "local")).save(name, value)
    return {"artifacts": {name: value.model_dump(mode="json")}, "log": [f"assembled {name}"]}


def write_changes(state: AidlcState, diff: Any, root: str | Path | None = None) -> None:
    sandbox = Path(root) if root else Path("runs") / state.get("run_id", "local") / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    for change in diff.changes:
        target = sandbox / change.path
        if change.action == "delete":
            target.unlink(missing_ok=True)
        elif change.content is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content, encoding="utf-8")
