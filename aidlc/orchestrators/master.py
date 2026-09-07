"""Master durable AIDLC state machine."""

import os
import sqlite3
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from aidlc.core.artifacts import ChangeRequest
from aidlc.core.state import AidlcState
from aidlc.orchestrators.build import build_graph
from aidlc.orchestrators.deploy import build_deploy_graph
from aidlc.orchestrators.design import build_design_graph
from aidlc.orchestrators.requirements import build_requirements_graph
from aidlc.orchestrators.test_eval import build_test_eval_graph
from aidlc.storage.factory import get_run_repository

_connections: list[sqlite3.Connection] = []
_postgres_contexts = []
_postgres_setup = False


def _default_checkpointer():
    global _postgres_setup
    database_url = os.getenv("AIDLC_DATABASE_URL")
    if database_url:
        from langgraph.checkpoint.postgres import PostgresSaver

        context = PostgresSaver.from_conn_string(database_url)
        checkpointer = context.__enter__()
        _postgres_contexts.append(context)
        if not _postgres_setup:
            checkpointer.setup()
            _postgres_setup = True
        return checkpointer
    runs_dir = os.getenv("AIDLC_RUNS_DIR", "./runs")
    os.makedirs(runs_dir, exist_ok=True)
    path = os.path.join(runs_dir, "checkpoints.sqlite")
    connection = sqlite3.connect(path, check_same_thread=False, timeout=30)
    _connections.append(connection)
    return SqliteSaver(connection)


def _phase_node(graph, phase: str):
    def node(state: AidlcState):
        result = graph.invoke(state)
        old_scorecards = state.get("scorecards", [])
        old_decisions = state.get("gate_decisions", [])
        old_log = state.get("log", [])
        return {
            "artifacts": result.get("artifacts", {}),
            "scorecards": result.get("scorecards", [])[len(old_scorecards) :],
            "gate_decisions": result.get("gate_decisions", [])[len(old_decisions) :],
            "log": result.get("log", [])[len(old_log) :],
            "phase": phase,
            "status": result.get("status", state.get("status", "running")),
        }

    return node


def _route_update(phase: str):
    def node(state: AidlcState):
        scorecard = state.get("scorecards", [])[-1]
        decision = state.get("gate_decisions", [])[-1]
        updates: dict = {}
        retries = dict(state.get("retries", {}))
        if decision.get("decision") == "block" or state.get("status") == "blocked":
            updates["status"] = "blocked"
            return updates
        if not scorecard.get("passed", False):
            count = retries.get(phase, 0)
            if count < 2:
                retries[phase] = count + 1
                updates["retries"] = retries
                updates["log"] = [f"{phase}:retry {retries[phase]} after evaluator feedback"]
            else:
                updates["status"] = "blocked"
            return updates
        if phase == "test_eval":
            items = state.get("artifacts", {}).get("triage_report", {}).get("items", [])
            target = next((item for item in items if item.get("target_phase")), None)
            if target:
                hops = retries.get("backward", 0)
                if hops >= 2:
                    updates["status"] = "blocked"
                    return updates
                retries["backward"] = hops + 1
                request = ChangeRequest(
                    id=f"CR-{len(state.get('change_requests', [])) + 1}",
                    source_phase="test_eval",
                    target_phase=target["target_phase"],
                    reason=target.get("summary", "Regression triage requested a change"),
                    details=[target.get("test_id", ""), target.get("summary", "")],
                )
                updates["retries"] = retries
                updates["change_requests"] = [
                    *state.get("change_requests", []),
                    request.model_dump(),
                ]
                updates["log"] = [f"test_eval:backward route to {target['target_phase']}"]
        return updates

    return node


def _next_route(phase: str):
    def route(state: AidlcState):
        if state.get("status") in {"blocked", "awaiting_approval"}:
            return "end"
        if not state.get("scorecards", [])[-1].get("passed", False):
            return phase
        if phase == "requirements":
            return "design"
        if phase == "design":
            return "build"
        if phase == "build":
            return "test_eval"
        if phase == "test_eval":
            items = state.get("artifacts", {}).get("triage_report", {}).get("items", [])
            target = next(
                (item.get("target_phase") for item in items if item.get("target_phase")), None
            )
            return target or "deploy"
        return "end"

    return route


def build_master_graph(checkpointer=None):
    graph = StateGraph(AidlcState)
    phases = [
        ("requirements", build_requirements_graph()),
        ("design", build_design_graph()),
        ("build", build_graph()),
        ("test_eval", build_test_eval_graph()),
        ("deploy", build_deploy_graph()),
    ]
    for name, subgraph in phases:
        graph.add_node(name, _phase_node(subgraph, name))
        graph.add_node(f"route_{name}", _route_update(name))
    graph.add_edge(START, "requirements")
    phase_names = [name for name, _ in phases]
    next_map = {
        "requirements": "design",
        "design": "build",
        "build": "test_eval",
        "test_eval": "deploy",
        "deploy": END,
    }
    for phase in phase_names:
        route_node = f"route_{phase}"
        graph.add_edge(phase, route_node)
        destinations = {"end": END, phase: phase}
        if phase == "test_eval":
            destinations.update({"design": "design", "build": "build", "deploy": "deploy"})
        elif phase in next_map and next_map[phase] != END:
            destinations[next_map[phase]] = next_map[phase]
        graph.add_conditional_edges(route_node, _next_route(phase), destinations)
    return graph.compile(checkpointer=checkpointer or _default_checkpointer())


def _initial_state(intent: str, context: dict | None, run_id: str) -> AidlcState:
    return {
        "run_id": run_id,
        "intent": intent,
        "context": context
        or {
            "repo_path": None,
            "target_env": "simulation",
            "risk_level": "low",
            "budget_usd": 25.0,
            "stakeholders": [],
        },
        "phase": "requirements",
        "artifacts": {},
        "scorecards": [],
        "gate_decisions": [],
        "change_requests": [],
        "retries": {},
        "log": [],
        "status": "running",
    }


def run_pipeline(
    intent: str,
    context: dict | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
) -> AidlcState:
    run_id = run_id or str(uuid.uuid4())
    run_context = context or {
        "repo_path": None,
        "target_env": "simulation",
        "risk_level": "low",
        "budget_usd": 25.0,
        "stakeholders": [],
    }
    get_run_repository().upsert_run(
        run_id,
        intent,
        run_context,
        "running",
        "requirements",
        run_context.get("requested_by", os.getenv("AIDLC_USER", "local")),
    )
    graph = build_master_graph()
    config = {"configurable": {"thread_id": thread_id or run_id}}
    result = graph.invoke(_initial_state(intent, context, run_id), config=config)
    checkpoint = graph.get_state(config)
    if any(task.interrupts for task in checkpoint.tasks):
        result["status"] = "awaiting_approval"
    get_run_repository().update_status(
        run_id, result["status"], result.get("phase", "requirements")
    )
    return result


def resume_run(run_id: str, approved: bool, by: str) -> AidlcState:
    graph = build_master_graph()
    config = {"configurable": {"thread_id": run_id}}
    result = graph.invoke(
        Command(resume={"approved": approved, "by": by}),
        config=config,
    )
    checkpoint = graph.get_state(config)
    if any(task.interrupts for task in checkpoint.tasks):
        result["status"] = "awaiting_approval"
    get_run_repository().update_status(
        run_id, result["status"], result.get("phase", "requirements")
    )
    return result
