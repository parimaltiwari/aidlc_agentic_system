"""Async Temporal client helpers used by the CLI and API."""

from __future__ import annotations

import os
import uuid

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from aidlc.distributed import TASK_QUEUE
from aidlc.distributed.models import GateApproval, RunStatus, StartRun
from aidlc.distributed.workflow import AidlcRunWorkflow
from aidlc.storage.factory import get_run_repository


async def get_client() -> Client:
    return await Client.connect(
        os.getenv("AIDLC_TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("AIDLC_TEMPORAL_NAMESPACE", "default"),
    )


async def start_run(
    intent: str,
    context: dict,
    requested_by: str,
    auto_approve: bool,
) -> str:
    run_id = str(uuid.uuid4())
    get_run_repository().upsert_run(
        run_id,
        intent,
        context,
        "running",
        "requirements",
        requested_by,
    )
    client = await get_client()
    await client.start_workflow(
        AidlcRunWorkflow.run,
        StartRun(run_id, intent, context, requested_by, auto_approve),
        id=run_id,
        task_queue=TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    return run_id


async def approve(run_id: str, approved: bool, by: str) -> None:
    client = await get_client()
    handle = client.get_workflow_handle(run_id)
    current: RunStatus = await handle.query(AidlcRunWorkflow.get_status)
    gate = current.awaiting_gate or "requirements:1"
    phase, attempt = gate.rsplit(":", 1)
    await handle.signal(
        AidlcRunWorkflow.approve_gate,
        GateApproval(phase, int(attempt), approved, by),
    )


async def status(run_id: str) -> RunStatus:
    client = await get_client()
    return await client.get_workflow_handle(run_id).query(AidlcRunWorkflow.get_status)
