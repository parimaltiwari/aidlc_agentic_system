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
from aidlc.core.evals import TestEvalEvaluator
from aidlc.core.artifacts import QualityReport, TraceabilityMatrix
from aidlc.core.state import AidlcState
from aidlc.storage.factory import get_artifact_store
from aidlc.orchestrators.base import agent_node, assemble


def plan_node(state: AidlcState):
    plan = TestPlannerAgent().run(state)
    package = dict(state.get("artifacts", {}).get("design_package", {}))
    traceability = package.get("traceability", {"rows": []})
    test_by_requirement: dict[str, list[str]] = {}
    for case in plan.cases:
        for requirement_id in case.requirement_ids:
            test_by_requirement.setdefault(requirement_id, []).append(case.id)
    rows = []
    for row in traceability.get("rows", []):
        rows.append({**row, "test_ids": test_by_requirement.get(row["requirement_id"], [])})
    package["traceability"] = TraceabilityMatrix(rows=rows).model_dump(mode="json")
    get_artifact_store(state.get("run_id", "local")).save("test_plan", plan)
    return {
        "artifacts": {"test_plan": plan.model_dump(mode="json"), "design_package": package},
        "log": ["test_eval:test-planner updated traceability"],
    }


def quality_node(state: AidlcState):
    artifacts = state.get("artifacts", {})
    requirements = {
        item["id"] for item in artifacts.get("requirements_spec", {}).get("requirements", [])
    }
    cases = artifacts.get("test_plan", {}).get("cases", [])
    covered = {rid for case in cases for rid in case.get("requirement_ids", [])}
    results = artifacts.get("test_results", {}).get("results", [])
    all_passed = bool(results) and all(result.get("passed", False) for result in results)
    coverage = {requirement_id: requirement_id in covered for requirement_id in requirements}
    summary = QualityAgent().run(state).summary
    report = QualityReport(
        go=bool(requirements) and requirements <= covered and all_passed,
        coverage_by_requirement=coverage,
        summary=summary,
        results=[artifacts.get("test_results", {})],
    )
    return assemble(state, "quality_report", report)


def build_test_eval_graph():
    graph = StateGraph(AidlcState)
    nodes = [
        ("plan", TestPlannerAgent()),
        ("integration", IntegrationAPITestAgent()),
        ("e2e", E2ETestAgent()),
        ("performance", PerformanceLoadAgent()),
        ("security", SecurityTestAgent()),
        ("triage", RegressionTriageAgent()),
    ]
    for name, agent in nodes:
        graph.add_node(name, plan_node if name == "plan" else agent_node(agent))
    graph.add_node("gate", gate_node("test_eval"))
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "integration")
    graph.add_edge("integration", "e2e")
    graph.add_edge("e2e", "performance")
    graph.add_edge("performance", "security")
    graph.add_edge("security", "triage")
    graph.add_edge("triage", "quality")
    graph.add_node("quality", quality_node)
    graph.add_node("evaluate", agent_node(TestEvalEvaluator()))
    graph.add_edge("quality", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
