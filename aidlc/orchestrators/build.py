"""Build orchestration over the design work plan."""

import os
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from aidlc.agents.build.agents import (
    CoderAgent,
    CodeReviewerAgent,
    IntegratorAgent,
    UnitTestWriterAgent,
)
from aidlc.core.artifacts import CodeDiff, EnvReport, StaticReport, ToolResult
from aidlc.core.evals import BuildEvaluator
from aidlc.core.gate import gate_node
from aidlc.core.state import AidlcState
from aidlc.core.store import ArtifactStore
from aidlc.orchestrators.base import assemble, write_changes
from aidlc.tools import static_analysis, test_runner
from aidlc.tools.git_tool import commit, copy_repo


def _sandbox(state: AidlcState) -> Path:
    return Path(os.getenv("AIDLC_RUNS_DIR", "./runs")) / state.get("run_id", "local") / "sandbox"


def scaffold_node(state: AidlcState):
    sandbox = _sandbox(state)
    (sandbox / "aidlc_generated").mkdir(parents=True, exist_ok=True)
    (sandbox / "tests").mkdir(parents=True, exist_ok=True)
    (sandbox / "aidlc_generated" / "__init__.py").write_text("", encoding="utf-8")
    (sandbox / "tests" / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).parents[1]))\n",
        encoding="utf-8",
    )
    report = EnvReport(
        python_version=sys.version.split()[0],
        tools_available=["python", "ruff", "pytest"],
        baseline_ok=True,
    )
    ArtifactStore(state.get("run_id", "local")).save("env_report", report)
    return {
        "artifacts": {"env_report": report.model_dump(mode="json")},
        "log": ["build:scaffold-env"],
    }


def _ordered_items(state: AidlcState) -> list[dict]:
    items = (
        state.get("artifacts", {}).get("design_package", {}).get("work_plan", {}).get("items", [])
    )
    by_id = {item["id"]: item for item in items}
    ordered: list[dict] = []
    remaining = set(by_id)
    while remaining:
        ready = sorted(
            item_id
            for item_id in remaining
            if all(dep not in remaining for dep in by_id[item_id].get("depends_on", []))
        )
        if not ready:
            raise ValueError("Work plan dependencies contain a cycle")
        ordered.extend(by_id[item_id] for item_id in ready)
        remaining.difference_update(ready)
    return ordered


def work_items_node(state: AidlcState):
    updates = {}
    logs = []
    for item in _ordered_items(state):
        work_id = item["id"]
        coder = CoderAgent(work_id)
        diff = coder.run(state)
        write_changes(state, diff, root=_sandbox(state))
        updates[coder.output_key] = diff.model_dump(mode="json")
        writer = UnitTestWriterAgent(work_id)
        writer_state = {**state, "artifacts": {**state.get("artifacts", {}), **updates}}
        test_diff = writer.run(writer_state)
        write_changes(state, test_diff, root=_sandbox(state))
        updates[writer.output_key] = test_diff.model_dump(mode="json")
        reviewer = CodeReviewerAgent(work_id)
        review = reviewer.run(writer_state)
        updates[reviewer.output_key] = review.model_dump(mode="json")
        logs.append(f"build:completed {work_id}")
    return {"artifacts": updates, "log": logs}


def static_and_tests_node(state: AidlcState):
    sandbox = _sandbox(state)
    static_ok, static_output = static_analysis.run_static_analysis(sandbox)
    test_ok, test_output = test_runner.run_tests(sandbox)
    report = StaticReport(
        tool_results=[
            ToolResult(tool="ruff", passed=static_ok, output=static_output),
            ToolResult(tool="pytest", passed=test_ok, output=test_output),
        ],
        passed=static_ok and test_ok,
    )
    return assemble(state, "static_report", report)


def integrator_node(state: AidlcState):
    result = IntegratorAgent().run(state)
    repo_path = state.get("context", {}).get("repo_path")
    if repo_path:
        destination = _sandbox(state) / "repo"
        copy_repo(repo_path, destination)
        for key, value in state.get("artifacts", {}).items():
            if key.startswith("code_diff_"):
                write_changes(
                    {"run_id": state.get("run_id", "local")},
                    CodeDiff.model_validate(value),
                    root=destination,
                )
        commit_id = commit(destination, f"AIDLC run {state.get('run_id', 'local')}")
        result = result.model_copy(
            update={
                "branch": f"aidlc/{state.get('run_id', 'local')}",
                "commits": [commit_id],
            }
        )
    ArtifactStore(state.get("run_id", "local")).save("pull_request_artifact", result)
    return {
        "artifacts": {"pull_request_artifact": result.model_dump(mode="json")},
        "log": ["build:integrator produced pull_request_artifact"],
    }


def build_graph():
    graph = StateGraph(AidlcState)
    graph.add_node("scaffold", scaffold_node)
    graph.add_node("work_items", work_items_node)
    graph.add_node("static_and_tests", static_and_tests_node)
    graph.add_node("integrator", integrator_node)
    graph.add_node("evaluate", BuildEvaluator().as_node())
    graph.add_node("gate", gate_node("build"))
    graph.add_edge(START, "scaffold")
    graph.add_edge("scaffold", "work_items")
    graph.add_edge("work_items", "static_and_tests")
    graph.add_edge("static_and_tests", "integrator")
    graph.add_edge("integrator", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
