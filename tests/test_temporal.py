import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker
from temporalio.testing import WorkflowEnvironment

from aidlc.core.artifacts import TriageItem, TriageReport
from aidlc.core.llm import MockLLM
from aidlc.distributed import TASK_QUEUE
from aidlc.distributed.activities import record_status, run_phase
from aidlc.distributed.models import GateApproval, StartRun
from aidlc.distributed.workflow import AidlcRunWorkflow
from aidlc.storage.factory import get_run_repository


async def _wait_for_gate(handle, client):
    for _ in range(200):
        status = await handle.query(AidlcRunWorkflow.get_status)
        if status.awaiting_gate:
            return status.awaiting_gate
        await asyncio.sleep(0.01)
    raise AssertionError("workflow did not reach an approval gate")


@asynccontextmanager
async def _worker(environment):
    executor = ThreadPoolExecutor(max_workers=8)
    async with Worker(
        environment.client,
        task_queue=TASK_QUEUE,
        workflows=[AidlcRunWorkflow],
        activities=[run_phase, record_status],
        activity_executor=executor,
    ):
        yield
    executor.shutdown(wait=True)


def test_temporal_auto_approve_completes(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("AIDLC_RUNS_DIR", str(tmp_path))
        monkeypatch.delenv("AIDLC_DATABASE_URL", raising=False)
        monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with _worker(environment):
                run_id = str(uuid.uuid4())
                get_run_repository().upsert_run(
                    run_id,
                    "Add password reset",
                    {"risk_level": "low", "target_env": "simulation"},
                    "running",
                    "requirements",
                    "test",
                )
                handle = await environment.client.start_workflow(
                    AidlcRunWorkflow.run,
                    StartRun(
                        run_id,
                        "Add password reset",
                        {"risk_level": "low", "target_env": "simulation"},
                        "test",
                        True,
                    ),
                    id=run_id,
                    task_queue=TASK_QUEUE,
                )
                result = await handle.result()
                assert result.status == "completed"
                gates = (tmp_path / run_id / "gates.jsonl").read_text().splitlines()
                assert len(gates) == 5

    asyncio.run(run())


def test_temporal_approval_signal_completes_high_risk_run(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("AIDLC_RUNS_DIR", str(tmp_path))
        monkeypatch.delenv("AIDLC_DATABASE_URL", raising=False)
        monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with _worker(environment):
                run_id = str(uuid.uuid4())
                get_run_repository().upsert_run(
                    run_id,
                    "Add password reset",
                    {"risk_level": "high", "target_env": "simulation"},
                    "running",
                    "requirements",
                    "test",
                )
                handle = await environment.client.start_workflow(
                    AidlcRunWorkflow.run,
                    StartRun(
                        run_id,
                        "Add password reset",
                        {"risk_level": "high", "target_env": "simulation"},
                        "test",
                        False,
                    ),
                    id=run_id,
                    task_queue=TASK_QUEUE,
                )
                for _ in range(5):
                    gate = await _wait_for_gate(handle, environment.client)
                    phase, attempt = gate.split(":")
                    await handle.signal(
                        AidlcRunWorkflow.approve_gate,
                        GateApproval(phase, int(attempt), True, "qa"),
                    )
                    await asyncio.sleep(0.02)
                result = await handle.result()
                assert result.status == "completed"

    asyncio.run(run())


def test_temporal_reject_signal_blocks(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setenv("AIDLC_RUNS_DIR", str(tmp_path))
        monkeypatch.delenv("AIDLC_DATABASE_URL", raising=False)
        monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with _worker(environment):
                run_id = str(uuid.uuid4())
                get_run_repository().upsert_run(
                    run_id,
                    "Add password reset",
                    {"risk_level": "high", "target_env": "simulation"},
                    "running",
                    "requirements",
                    "test",
                )
                handle = await environment.client.start_workflow(
                    AidlcRunWorkflow.run,
                    StartRun(
                        run_id,
                        "Add password reset",
                        {"risk_level": "high", "target_env": "simulation"},
                        "test",
                        False,
                    ),
                    id=run_id,
                    task_queue=TASK_QUEUE,
                )
                gate = await _wait_for_gate(handle, environment.client)
                phase, attempt = gate.split(":")
                await handle.signal(
                    AidlcRunWorkflow.approve_gate,
                    GateApproval(phase, int(attempt), False, "qa"),
                )
                result = await handle.result()
                assert result.status == "blocked"

    asyncio.run(run())


def test_temporal_triage_records_change_request_and_reenters_build(tmp_path, monkeypatch):
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

    async def run():
        monkeypatch.setenv("AIDLC_RUNS_DIR", str(tmp_path))
        monkeypatch.delenv("AIDLC_DATABASE_URL", raising=False)
        monkeypatch.delenv("AIDLC_AUTO_APPROVE", raising=False)
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with _worker(environment):
                run_id = str(uuid.uuid4())
                get_run_repository().upsert_run(
                    run_id,
                    "Add password reset",
                    {"risk_level": "low", "target_env": "simulation"},
                    "running",
                    "requirements",
                    "test",
                )
                handle = await environment.client.start_workflow(
                    AidlcRunWorkflow.run,
                    StartRun(
                        run_id,
                        "Add password reset",
                        {"risk_level": "low", "target_env": "simulation"},
                        "test",
                        True,
                    ),
                    id=run_id,
                    task_queue=TASK_QUEUE,
                )
                result = await handle.result()
                assert result.status == "completed"
                change_requests = (
                    (tmp_path / run_id / "change_requests.jsonl").read_text().splitlines()
                )
                assert len(change_requests) == 1
                gates = [
                    json.loads(line)
                    for line in (tmp_path / run_id / "gates.jsonl").read_text().splitlines()
                ]
                assert sum(item["phase"] == "build" for item in gates) == 2

    asyncio.run(run())
