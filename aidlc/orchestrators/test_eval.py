from langgraph.graph import END, START, StateGraph

from aidlc.agents.test_eval.agents import (
    E2ETestAgent,
    IntegrationAPITestAgent,
    PerformanceLoadAgent,
    QualityAgent,
    RegressionTriageAgent,
    SecurityTestAgent,
    TestPlannerAgent,
)
from aidlc.core.gate import gate_node
from aidlc.core.state import AidlcState
from aidlc.orchestrators.base import agent_node


def build_test_eval_graph():
    graph = StateGraph(AidlcState)
    nodes = [
        ("plan", TestPlannerAgent()),
        ("integration", IntegrationAPITestAgent()),
        ("e2e", E2ETestAgent()),
        ("performance", PerformanceLoadAgent()),
        ("security", SecurityTestAgent()),
        ("triage", RegressionTriageAgent()),
        ("quality", QualityAgent()),
    ]
    for name, agent in nodes:
        graph.add_node(name, agent_node(agent))
    graph.add_node("gate", gate_node("test_eval"))
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "integration")
    graph.add_edge("integration", "e2e")
    graph.add_edge("e2e", "performance")
    graph.add_edge("performance", "security")
    graph.add_edge("security", "triage")
    graph.add_edge("triage", "quality")
    graph.add_node(
        "evaluate",
        agent_node(
            __import__("aidlc.core.evals", fromlist=["TestEvalEvaluator"]).TestEvalEvaluator()
        ),
    )
    graph.add_edge("quality", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
