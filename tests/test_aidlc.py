import os

from fastapi.testclient import TestClient

from aidlc.core.artifacts import Requirement, RequirementsSpec
from aidlc.core.gate import GatePolicy
from aidlc.orchestrators.master import run_pipeline
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
