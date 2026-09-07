"""Deterministic Temporal workflow for cross-phase AIDLC routing."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from aidlc.distributed.activities import record_status, run_phase
    from aidlc.distributed.models import GateApproval, PhaseInput, PhaseResult, RunStatus, StartRun
    from aidlc.distributed import TASK_QUEUE


@workflow.defn
class AidlcRunWorkflow:
    def __init__(self) -> None:
        self.approvals: dict[str, GateApproval] = {}
        self.status = "running"
        self.phase = "requirements"
        self.retries: dict[str, int] = {}
        self.change_requests: list[dict] = []
        self.run_id = ""
        self.auto_approve = False

    @workflow.run
    async def run(self, request: StartRun) -> RunStatus:
        self.run_id = request.run_id
        self.auto_approve = request.auto_approve
        phase = "requirements"
        while phase != "end":
            self.phase = phase
            attempt = self.retries.get(phase, 0) + 1
            result: PhaseResult = await workflow.execute_activity(
                run_phase,
                PhaseInput(
                    request.run_id,
                    phase,
                    attempt,
                    list(self.change_requests),
                    request.auto_approve,
                ),
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            decision = await self._gate(phase, attempt, result)
            phase = self._route(phase, result, decision)
        return RunStatus(self.run_id, self.status, self.phase)

    async def _gate(self, phase: str, attempt: int, result: PhaseResult) -> dict:
        gate = dict(result.gate)
        if gate.get("decision") == "block":
            self.status = "blocked"
            await self._record_status()
            return gate
        if gate.get("decision") == "auto" or self.auto_approve:
            self.status = "completed" if phase == "deploy" else "running"
            await self._record_status()
            return gate
        self.status = "awaiting_approval"
        await self._record_status()
        key = f"{phase}:{attempt}"
        try:
            await workflow.wait_condition(
                lambda: key in self.approvals,
                timeout=timedelta(days=14),
            )
        except TimeoutError:
            self.status = "blocked"
            await self._record_status()
            return {**gate, "decision": "block", "reason": "approval_timeout", "approved": False}
        approval = self.approvals[key]
        if not approval.approved:
            self.status = "blocked"
            await self._record_status()
            return {
                **gate,
                "decision": "block",
                "approved": False,
                "approved_by": approval.by,
                "reason": "Approval rejected",
            }
        self.status = "completed" if phase == "deploy" else "running"
        await self._record_status()
        return {**gate, "decision": "auto", "approved": True, "approved_by": approval.by}

    def _route(self, phase: str, result: PhaseResult, decision: dict) -> str:
        if decision.get("decision") == "block" or self.status == "blocked":
            return "end"
        if not result.scorecard_passed:
            count = self.retries.get(phase, 0)
            if count < 2:
                self.retries[phase] = count + 1
                return phase
            self.status = "blocked"
            return "end"
        if phase == "test_eval" and result.triage_target:
            hops = self.retries.get("backward", 0)
            if hops >= 2:
                self.status = "blocked"
                return "end"
            self.retries["backward"] = hops + 1
            request_id = f"CR-{len(self.change_requests) + 1}"
            self.change_requests.append(
                {
                    "id": request_id,
                    "source_phase": "test_eval",
                    "target_phase": result.triage_target,
                    "reason": "Regression triage requested a change",
                    "details": [result.triage_target],
                }
            )
            return result.triage_target
        next_phase = {
            "requirements": "design",
            "design": "build",
            "build": "test_eval",
            "test_eval": "deploy",
            "deploy": "end",
        }
        return next_phase[phase]

    async def _record_status(self) -> None:
        await workflow.execute_activity(
            record_status,
            args=[self.run_id, self.status, self.phase],
            task_queue=TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=1),
        )

    @workflow.signal
    def approve_gate(self, approval: GateApproval) -> None:
        self.approvals[f"{approval.phase}:{approval.attempt}"] = approval

    @workflow.query
    def get_status(self) -> RunStatus:
        awaiting = None
        if self.status == "awaiting_approval":
            awaiting = f"{self.phase}:{self.retries.get(self.phase, 0) + 1}"
        return RunStatus(self.run_id, self.status, self.phase, awaiting)
