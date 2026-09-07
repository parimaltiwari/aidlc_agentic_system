"""Temporal worker entrypoint."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack

from temporalio.client import Client
from temporalio.worker import Worker

from aidlc.distributed import TASK_QUEUE
from aidlc.distributed.activities import record_status, run_phase
from aidlc.distributed.workflow import AidlcRunWorkflow


async def run_worker(
    address: str = "localhost:7233",
    namespace: str = "default",
    queues: list[str] | None = None,
) -> None:
    client = await Client.connect(address, namespace=namespace)
    executor = ThreadPoolExecutor(max_workers=16)
    try:
        workers = [
            Worker(
                client,
                task_queue=queue,
                workflows=[AidlcRunWorkflow],
                activities=[run_phase, record_status],
                activity_executor=executor,
            )
            for queue in queues or [TASK_QUEUE]
        ]
        async with AsyncExitStack() as stack:
            for worker in workers:
                await stack.enter_async_context(worker)
            await asyncio.Event().wait()
    finally:
        executor.shutdown(wait=True)
