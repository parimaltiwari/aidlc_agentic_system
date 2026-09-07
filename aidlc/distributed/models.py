"""Small Temporal payload models."""

from dataclasses import dataclass, field


@dataclass
class StartRun:
    run_id: str
    intent: str
    context: dict
    requested_by: str
    auto_approve: bool


@dataclass
class PhaseInput:
    run_id: str
    phase: str
    attempt: int
    change_requests: list[dict] = field(default_factory=list)
    auto_approve: bool = False


@dataclass
class PhaseResult:
    phase: str
    attempt: int
    gate: dict
    scorecard_passed: bool
    status: str
    triage_target: str | None = None


@dataclass
class GateApproval:
    phase: str
    attempt: int
    approved: bool
    by: str


@dataclass
class RunStatus:
    run_id: str
    status: str
    phase: str
    awaiting_gate: str | None = None
