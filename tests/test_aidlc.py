import os
import time

from fastapi.testclient import TestClient

from aidlc.core.artifacts import (
    Requirement,
    RequirementsSpec,
    TriageItem,
    TriageReport,
)
from aidlc.core.evals import RequirementsEvaluator
from aidlc.core.gate import GatePolicy
from aidlc.core.llm import MockLLM
from aidlc.orchestrators.build import build_graph
from aidlc.orchestrators.deploy import build_deploy_graph
from aidlc.orchestrators.design import build_design_graph
from aidlc.orchestrators.master import resume_run, run_pipeline
from aidlc.orchestrators.requirements import build_requirements_graph
from aidlc.orchestrators.test_eval import build_test_eval_graph
from aidlc.services.api import app


def test_artifact_round_trip():
    value = Requirement(
        id="REQ-1",
        kind="functional",
        title="x",
        description="y",
        acceptance_criteria=["z"],
        priority="must",
    )
    assert Requirement.model_validate_json(value.model_dump_json()) == value
    assert (
        RequirementsSpec(
            title="x", problem_statement="y", requirements=[value], out_of_scope=[], assumptions=[]
        )
        .requirements[0]
        .id
        == "REQ-1"
    )


def test_gate_policy_matrix():
    from aidlc.core.artifacts import EvalScorecard

    score = EvalScorecard(
        phase="x", agent="x", scores={"x": 0.9}, overall=0.9, passed=True, feedback=[]
    )
    assert GatePolicy().decide(score, "low").decision == "auto"
    assert GatePolicy().decide(score, "high").decision == "review"
    failed = score.model_copy(update={"passed": False, "overall": 0.1})
    assert GatePolicy().decide(failed, "low", retries=2).decision == "block"


def test_full_pipeline():
    os.environ["AIDLC_AUTO_APPROVE"] = "1"
    result = run_pipeline("Add password reset", {"risk_level": "low", "target_env": "simulation"})
    assert result["status"] == "completed"
    assert len(result["gate_decisions"]) == 5
    rows = result["artifacts"]["design_package"]["traceability"]["rows"]
    assert all(row["work_item_ids"] and row["test_ids"] for row in rows)


def test_api_smoke():
    os.environ["AIDLC_AUTO_APPROVE"] = "1"
    client = TestClient(app)
    response = client.post(
        "/runs",
        json={
            "intent": "Add password reset",
            "context": {"risk_level": "low", "target_env": "simulation"},
        },
    )
    assert response.status_code == 200
    assert response.json()["run_id"]


def test_phase_subgraphs_with_prior_artifacts():
    os.environ["AIDLC_AUTO_APPROVE"] = "1"
    result = run_pipeline("Add password reset", {"risk_level": "low", "target_env": "simulation"})
    state = {
        "run_id": result["run_id"],
        "intent": "Add password reset",
        "context": {"risk_level": "low", "target_env": "simulation"},
        "artifacts": result["artifacts"],
        "scorecards": [],
        "gate_decisions": [],
        "change_requests": [],
        "retries": {},
        "log": [],
        "status": "running",
    }
    for graph in (
        build_requirements_graph(),
        build_design_graph(),
        build_graph(),
        build_test_eval_graph(),
        build_deploy_graph(),
    ):
        state = graph.invoke(state)
        assert state["status"] in {"running", "completed"}


def test_triage_routes_back_to_build(monkeypatch):
    os.environ["AIDLC_AUTO_APPROVE"] = "1"
    calls = 0

    def triage(_system, _user):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TriageReport(
                items=[
                    TriageItem(
                        test_id="T-1",
                        classification="product_bug",
                        target_phase="build",
                        summary="Fix implementation",
                    )
                ]
            )
        return TriageReport(items=[])

    monkeypatch.setitem(MockLLM.registry, TriageReport, triage)
    result = run_pipeline("Add password reset", {"risk_level": "low", "target_env": "simulation"})
    assert len(result["change_requests"]) == 1
    assert sum(item["phase"] == "build" for item in result["gate_decisions"]) == 2


def test_failed_requirements_retry(monkeypatch):
    os.environ["AIDLC_AUTO_APPROVE"] = "1"
    original = RequirementsEvaluator
    original_checks = original.deterministic_checks
    calls = 0

    def checks(self, state):
        nonlocal calls
        calls += 1
        return (
            {"completeness": 0.0, "testability": 0.0, "compliance": 0.0}
            if calls == 1
            else original_checks(self, state)
        )

    monkeypatch.setattr(original, "deterministic_checks", checks)
    result = run_pipeline("Add password reset", {"risk_level": "low", "target_env": "simulation"})
    assert result["retries"]["requirements"] == 1
    assert result["status"] == "completed"


def test_high_risk_approval_resume(monkeypatch):
    monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
    result = run_pipeline(
        "Add password reset",
        {"risk_level": "high", "target_env": "simulation"},
    )
    assert result["status"] == "awaiting_approval"
    resumed = resume_run(result["run_id"], True, "qa")
    assert resumed["status"] == "awaiting_approval"
    assert resumed["run_id"] == result["run_id"]


def test_api_artifacts_and_approval(monkeypatch):
    monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
    client = TestClient(app)
    response = client.post(
        "/runs",
        json={
            "intent": "Add password reset",
            "context": {"risk_level": "high", "target_env": "simulation"},
        },
    )
    run_id = response.json()["run_id"]
    for _ in range(50):
        if client.get(f"/runs/{run_id}").json().get("status") == "awaiting_approval":
            break
        time.sleep(0.02)
    assert client.get(f"/runs/{run_id}/artifacts").status_code == 200
    approval = client.post(
        f"/runs/{run_id}/approve",
        json={"approved": True, "by": "qa"},
    )
    assert approval.status_code == 200
