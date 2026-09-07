from langgraph.graph import END, START, StateGraph

from aidlc.agents.deploy.agents import (
    DeploymentExecutorAgent,
    IaCConfigAgent,
    ObservabilityVerifierAgent,
    ReleaseManagerAgent,
    RollbackAgent,
)
from aidlc.core.evals import DeployEvaluator
from aidlc.core.gate import gate_node
from aidlc.core.state import AidlcState
from aidlc.orchestrators.base import agent_node


def build_deploy_graph():
    graph = StateGraph(AidlcState)
    nodes = [
        ("release", ReleaseManagerAgent()),
        ("infra", IaCConfigAgent()),
        ("deploy", DeploymentExecutorAgent()),
        ("soak", ObservabilityVerifierAgent()),
        ("rollback", RollbackAgent()),
        ("evaluate", DeployEvaluator()),
    ]
    for name, agent in nodes:
        graph.add_node(name, agent_node(agent))
    graph.add_node("gate", gate_node("deploy"))
    graph.add_edge(START, "release")
    graph.add_edge("release", "infra")
    graph.add_edge("infra", "deploy")
    graph.add_edge("deploy", "soak")
    graph.add_edge("soak", "rollback")
    graph.add_edge("rollback", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
