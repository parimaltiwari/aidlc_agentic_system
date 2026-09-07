from langgraph.graph import END, START, StateGraph

from aidlc.agents.build.agents import (
    CoderAgent,
    CodeReviewerAgent,
    IntegratorAgent,
    ScaffoldEnvAgent,
    StaticAnalysisAgent,
)
from aidlc.core.evals import BuildEvaluator
from aidlc.core.gate import gate_node
from aidlc.core.state import AidlcState
from aidlc.orchestrators.base import agent_node, write_changes


def coder_node(work_id: str):
    coder = CoderAgent(work_id)

    def node(state: AidlcState):
        result = coder.run(state)
        write_changes(state, result)
        from aidlc.core.store import ArtifactStore

        ArtifactStore(state.get("run_id", "local")).save(coder.output_key, result)
        return {
            "artifacts": {coder.output_key: result.model_dump(mode="json")},
            "log": [f"build:coder produced {coder.output_key}"],
        }

    return node


def integrator_node(state: AidlcState):
    from aidlc.core.store import ArtifactStore
    from aidlc.tools.git_tool import commit, copy_repo

    result = IntegratorAgent().run(state)
    repo_path = state.get("context", {}).get("repo_path")
    if repo_path:
        destination = f"runs/{state.get('run_id', 'local')}/sandbox/repo"
        copy_repo(repo_path, destination)
        for key, value in state.get("artifacts", {}).items():
            if key.startswith("code_diff_"):
                from aidlc.core.artifacts import CodeDiff

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
    graph.add_node("scaffold", agent_node(ScaffoldEnvAgent()))
    graph.add_node("coder_1", coder_node("WI-1"))
    graph.add_node("review_1", agent_node(CodeReviewerAgent("WI-1")))
    graph.add_node("coder_2", coder_node("WI-2"))
    graph.add_node("review_2", agent_node(CodeReviewerAgent("WI-2")))
    graph.add_node("static", agent_node(StaticAnalysisAgent()))
    graph.add_node("integrator", integrator_node)
    graph.add_node("evaluate", agent_node(BuildEvaluator()))
    graph.add_node("gate", gate_node("build"))
    graph.add_edge(START, "scaffold")
    graph.add_edge("scaffold", "coder_1")
    graph.add_edge("coder_1", "review_1")
    graph.add_edge("review_1", "coder_2")
    graph.add_edge("coder_2", "review_2")
    graph.add_edge("review_2", "static")
    graph.add_edge("static", "integrator")
    graph.add_edge("integrator", "evaluate")
    graph.add_edge("evaluate", "gate")
    graph.add_edge("gate", END)
    return graph.compile()
