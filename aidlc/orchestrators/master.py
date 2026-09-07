"""Master durable AIDLC state machine."""

import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from aidlc.core.state import AidlcState
from aidlc.orchestrators.build import build_graph
from aidlc.orchestrators.deploy import build_deploy_graph
from aidlc.orchestrators.design import build_design_graph
from aidlc.orchestrators.requirements import build_requirements_graph
from aidlc.orchestrators.test_eval import build_test_eval_graph


def _phase_node(graph, phase: str):
    def node(state: AidlcState):
        result = graph.invoke(state)
        scorecards = result.get("scorecards", [])
        old_scorecards = state.get("scorecards", [])
        decisions = result.get("gate_decisions", [])
        old_decisions = state.get("gate_decisions", [])
        log = result.get("log", [])
        old_log = state.get("log", [])
        return {
            "artifacts": result.get("artifacts", {}),
            "scorecards": scorecards[len(old_scorecards) :],
            "gate_decisions": decisions[len(old_decisions) :],
            "log": log[len(old_log) :],
            "phase": phase,
            "status": result.get("status", state.get("status", "running")),
        }

    return node


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
    graph.add_edge(START, "requirements")
    graph.add_edge("requirements", "design")
    graph.add_edge("design", "build")
    graph.add_edge("build", "test_eval")
    graph.add_edge("test_eval", "deploy")
    graph.add_edge("deploy", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_pipeline(
    intent: str,
    context: dict | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
) -> AidlcState:
    run_id = run_id or str(uuid.uuid4())
    initial: AidlcState = {
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
    graph = build_master_graph()
    config = {"configurable": {"thread_id": thread_id or run_id}}
    result = graph.invoke(initial, config=config)
    if result.get("status") == "completed" or len(result.get("gate_decisions", [])) == 5:
        result["status"] = "completed"
    return result
