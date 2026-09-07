import os
import uuid

import pytest


DATABASE_URL = os.getenv("AIDLC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set AIDLC_TEST_DATABASE_URL to run Postgres integration tests",
)


@pytest.fixture(autouse=True)
def postgres_environment(monkeypatch):
    monkeypatch.setenv("AIDLC_DATABASE_URL", DATABASE_URL)


def _stores():
    from aidlc.storage.postgres import (
        PostgresArtifactStore,
        PostgresRunRepository,
        PostgresTracer,
    )

    return PostgresArtifactStore, PostgresRunRepository, PostgresTracer


def _run_id() -> str:
    return f"pg-test-{uuid.uuid4()}"


def test_postgres_artifacts_are_versioned_and_deduplicated():
    ArtifactStore, RunRepository, _ = _stores()
    run_id = _run_id()
    repository = RunRepository()
    repository.upsert_run(run_id, "intent", {}, "running", "requirements", "test")
    store = ArtifactStore(run_id)

    first = store.save("requirements_spec", {"requirements": ["REQ-1"]})
    second = store.save("requirements_spec", {"requirements": ["REQ-1", "REQ-2"]})
    duplicate = store.save("requirements_spec", {"requirements": ["REQ-1", "REQ-2"]})

    assert first == "requirements_spec.v1"
    assert second == "requirements_spec.v2"
    assert duplicate == second
    assert store.read("requirements_spec") == {"requirements": ["REQ-1", "REQ-2"]}
    assert store.latest_all()["requirements_spec"] == {"requirements": ["REQ-1", "REQ-2"]}


def test_postgres_tracer_and_repository_roundtrip():
    _, RunRepository, Tracer = _stores()
    run_id = _run_id()
    repository = RunRepository()
    repository.upsert_run(
        run_id,
        "intent",
        {"risk_level": "low"},
        "running",
        "requirements",
        "test",
    )
    Tracer(run_id).record("agent", "requirements", 0.25, True, model="mock")
    repository.add_scorecard(
        run_id,
        "requirements",
        1,
        {
            "phase": "requirements",
            "agent": "requirements-evaluator",
            "scores": {"quality": 1.0},
            "overall": 1.0,
            "passed": True,
            "feedback": [],
        },
    )
    repository.add_gate_decision(
        run_id,
        "requirements",
        1,
        {"decision": "auto", "reason": "test", "approved": True},
        "test",
    )
    repository.add_change_request(
        run_id,
        {
            "id": "CR-1",
            "source_phase": "test_eval",
            "target_phase": "build",
            "reason": "test",
            "details": ["T-1"],
        },
    )
    repository.add_event(run_id, "info", "created")

    result = repository.get_run(run_id)
    assert result and result["intent"] == "intent"
    assert result["context"]["risk_level"] == "low"
    assert repository.latest_artifacts(run_id) == {}

    import psycopg

    with psycopg.connect(DATABASE_URL) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM agent_invocations WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM scorecards WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM gate_decisions WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM change_requests WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM run_events WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
            == 1
        )


def test_mock_pipeline_writes_postgres_history(monkeypatch):
    from aidlc.orchestrators.master import run_pipeline

    monkeypatch.setenv("AIDLC_AUTO_APPROVE", "1")
    run_id = _run_id()
    result = run_pipeline(
        "Add password reset",
        {"risk_level": "low", "target_env": "simulation"},
        run_id=run_id,
    )
    assert result["status"] == "completed"

    import psycopg

    with psycopg.connect(DATABASE_URL) as connection:
        for table in ("runs", "artifact_versions", "scorecards", "gate_decisions"):
            assert (
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE run_id = %s"
                    if table != "runs"
                    else "SELECT count(*) FROM runs WHERE id = %s",
                    (run_id,),
                ).fetchone()[0]
                > 0
            )


def test_postgres_approval_interrupt_and_resume(monkeypatch):
    from aidlc.orchestrators.master import resume_run, run_pipeline

    monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
    run_id = _run_id()
    result = run_pipeline(
        "Add password reset",
        {"risk_level": "high", "target_env": "simulation"},
        run_id=run_id,
    )
    assert result["status"] == "awaiting_approval"
    resumed = resume_run(run_id, True, "qa")
    assert resumed["run_id"] == run_id
    assert resumed["gate_decisions"][0]["approved"] is True

    import psycopg

    with psycopg.connect(DATABASE_URL) as connection:
        checkpoint_count = connection.execute(
            "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (run_id,)
        ).fetchone()[0]
    assert checkpoint_count > 0
