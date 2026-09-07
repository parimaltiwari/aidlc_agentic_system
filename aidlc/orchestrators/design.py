from langgraph.graph import END, START, StateGraph

from aidlc.agents.design.agents import (
    APIDataModelerAgent,
    CodebaseAnalystAgent,
    DataModelerAgent,
    SolutionArchitectAgent,
    TaskDecomposerAgent,
    ThreatModelAgent,
)
from aidlc.core.artifacts import DesignPackage, TraceRow, TraceabilityMatrix
from aidlc.core.evals import DesignEvaluator
from aidlc.core.gate import gate_node
from aidlc.core.state import AidlcState
from aidlc.orchestrators.base import agent_node, assemble


def package_node(state: AidlcState):
    artifacts = state.get("artifacts", {})
    reqs = artifacts.get("requirements_spec", {}).get("requirements", [])
    work = artifacts.get("work_plan", {"items": []})
    rows = [
        TraceRow(
            requirement_id=req["id"],
            design_refs=["ADR-1"],
            work_item_ids=[
                item["id"] for item in work["items"] if req["id"] in item["requirement_ids"]
            ],
            test_ids=["T-1", "T-2"],
        )
        for req in reqs
    ]
    package = DesignPackage(
        codebase_map=artifacts["codebase_map"],
        adrs=[artifacts["a_d_r"]],
        api_spec=artifacts["a_p_i_spec"],
        data_model=artifacts["data_model"],
        threat_model=artifacts["threat_model"],
        work_plan=work,
        traceability=TraceabilityMatrix(rows=rows),
    )
    return assemble(state, "design_package", package)


def build_design_graph():
    graph = StateGraph(AidlcState)
    agents = [
        ("codebase", CodebaseAnalystAgent()),
        ("adr", SolutionArchitectAgent()),
        ("api", APIDataModelerAgent()),
        ("data", DataModelerAgent()),
        ("threat", ThreatModelAgent()),
        ("work", TaskDecomposerAgent()),
    ]
    for name, agent in agents:
        graph.add_node(name, agent_node(agent))
    graph.add_node("package", package_node)
    graph.add_node("evaluate", agent_node(DesignEvaluator()))
    graph.add_node("gate", gate_node("design"))
    graph.add_edge(START, "codebase")
    graph.add_edge("codebase", "adr")
    graph.add_edge("adr", "api")
    graph.add_edge("api", "data")
    graph.add_edge("data", "threat")
    graph.add_edge("threat", "work")
    graph.add_edge("work", "package")
    graph.add_edge("package", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
