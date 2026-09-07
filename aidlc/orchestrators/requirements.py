from langgraph.graph import END, START, StateGraph

from aidlc.agents.requirements.agents import (
    DomainComplianceAgent,
    FeasibilityScopeAgent,
    IntakeContextAgent,
    RequirementsAuthorAgent,
    StakeholderClarifierAgent,
)
from aidlc.core.evals import RequirementsEvaluator
from aidlc.core.gate import gate_node
from aidlc.core.state import AidlcState
from aidlc.orchestrators.base import agent_node


def build_requirements_graph():
    graph = StateGraph(AidlcState)
    agents = {
        "intake": IntakeContextAgent(),
        "clarify": StakeholderClarifierAgent(),
        "author": RequirementsAuthorAgent(),
        "compliance": DomainComplianceAgent(),
        "scope": FeasibilityScopeAgent(),
        "evaluate": RequirementsEvaluator(),
    }
    for name, agent in agents.items():
        graph.add_node(name, agent_node(agent))
    graph.add_node("gate", gate_node("requirements"))
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "clarify")
    graph.add_edge("clarify", "author")
    graph.add_edge("author", "compliance")
    graph.add_edge("author", "scope")
    graph.add_edge("compliance", "evaluate")
    graph.add_edge("scope", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
