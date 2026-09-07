"""Protocols shared by AIDLC storage implementations."""

from typing import Any, Protocol


class ArtifactStoreProtocol(Protocol):
    def save(self, name: str, value: Any) -> str: ...

    def list(self) -> list[str]: ...

    def read(self, name: str) -> Any: ...

    def latest_all(self) -> dict[str, Any]: ...


class TracerProtocol(Protocol):
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
    ) -> None: ...


class RunRepository(Protocol):
    def upsert_run(
        self,
        run_id: str,
        intent: str,
        context: dict,
        status: str,
        phase: str,
        requested_by: str,
    ) -> None: ...

    def update_status(self, run_id: str, status: str, phase: str) -> None: ...

    def add_scorecard(self, run_id: str, phase: str, attempt: int, scorecard_dict: dict) -> None: ...

    def add_gate_decision(
        self,
        run_id: str,
        phase: str,
        attempt: int,
        decision_dict: dict,
        approval_by: str | None = None,
    ) -> None: ...

    def add_change_request(self, run_id: str, cr_dict: dict) -> None: ...

    def add_event(self, run_id: str, level: str, message: str) -> None: ...

    def get_run(self, run_id: str) -> dict | None: ...

    def latest_artifacts(self, run_id: str) -> dict[str, Any]: ...
