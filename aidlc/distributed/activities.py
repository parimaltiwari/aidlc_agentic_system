"""Temporal activities that execute existing LangGraph phase graphs."""

from __future__ import annotations

from temporalio import activity

from aidlc.core.state import AidlcState
from aidlc.orchestrators.build import build_graph
from aidlc.orchestrators.deploy import build_deploy_graph
from aidlc.orchestrators.design import build_design_graph
from aidlc.orchestrators.requirements import build_requirements_graph
from aidlc.orchestrators.test_eval import build_test_eval_graph
from aidlc.storage.factory import get_run_repository
from aidlc.distributed.models import PhaseInput, PhaseResult


def _phase_graph(phase: str):
    return {
        "requirements": build_requirements_graph,
        "design": build_design_graph,
        "build": build_graph,
        "test_eval": build_test_eval_graph,
        "deploy": build_deploy_graph,
    }[phase]()


def _heartbeat(message: str) -> None:
    try:
        activity.heartbeat(message)
    except RuntimeError:
        pass


@activity.defn
def run_phase(request: PhaseInput) -> PhaseResult:
    repository = get_run_repository()
    run = repository.get_run(request.run_id)
    if run is None:
        raise ValueError(f"Run {request.run_id} does not exist")
    artifacts = repository.latest_artifacts(request.run_id)
    stored_requests = run.get("change_requests", [])
    change_requests = request.change_requests or stored_requests
    known_ids = {item.get("id") for item in stored_requests}
    for change_request in change_requests:
        if change_request.get("id") not in known_ids:
            repository.add_change_request(request.run_id, change_request)
            known_ids.add(change_request.get("id"))
    context = dict(run.get("context", {}))
    context["_gate_mode"] = "record"
    context["_auto_approve"] = request.auto_approve
    state: AidlcState = {
        "run_id": request.run_id,
        "intent": run.get("intent", ""),
        "context": context,
        "phase": request.phase,
        "artifacts": artifacts,
        "scorecards": [],
        "gate_decisions": [],
        "change_requests": change_requests,
        "retries": {request.phase: request.attempt - 1},
        "log": [],
        "status": "running",
    }
    _heartbeat(f"{request.phase}:starting")
    result = _phase_graph(request.phase).invoke(state)
    _heartbeat(f"{request.phase}:finished")
    status = result.get("status", "running")
    repository.update_status(request.run_id, status, request.phase)
    scorecards = result.get("scorecards", [])
    gates = result.get("gate_decisions", [])
    triage_target = None
    for item in result.get("artifacts", {}).get("triage_report", {}).get("items", []):
        if item.get("target_phase"):
            triage_target = item["target_phase"]
            break
    return PhaseResult(
        phase=request.phase,
        attempt=request.attempt,
        gate=gates[-1] if gates else {},
        scorecard_passed=scorecards[-1].get("passed", False) if scorecards else False,
        status=status,
        triage_target=triage_target,
    )


@activity.defn
def record_status(run_id: str, status: str, phase: str) -> None:
    get_run_repository().update_status(run_id, status, phase)
