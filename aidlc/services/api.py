"""FastAPI run service."""

import asyncio
import os
import threading
import uuid
from typing import Any

from fastapi import FastAPI
from aidlc.orchestrators.master import resume_run, run_pipeline
from aidlc.storage.factory import get_run_repository

app = FastAPI(title="AIDLC API")
_runs: dict[str, dict[str, Any]] = {}


def _run(run_id: str, intent: str, context: dict):
    result = run_pipeline(intent, context, run_id=run_id)
    _runs[run_id] = result


@app.post("/runs")
def create_run(payload: dict):
    context = payload.get("context", {"risk_level": "low", "target_env": "simulation"})
    if os.getenv("AIDLC_EXECUTION") == "temporal":
        from aidlc.distributed.client import start_run

        run_id = asyncio.run(
            start_run(
                payload["intent"],
                context,
                payload.get("requested_by", os.getenv("AIDLC_USER", "api")),
                bool(payload.get("auto_approve", False)),
            )
        )
        return {"run_id": run_id, "status": "running"}
    run_id = str(uuid.uuid4())
    _runs[run_id] = {"run_id": run_id, "status": "running", "phase": "requirements"}
    threading.Thread(target=_run, args=(run_id, payload["intent"], context), daemon=True).start()
    return {"run_id": run_id}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    if os.getenv("AIDLC_EXECUTION") == "temporal":
        from aidlc.distributed.client import status

        current = asyncio.run(status(run_id))
        return {
            "run_id": current.run_id,
            "status": current.status,
            "phase": current.phase,
            "awaiting_gate": current.awaiting_gate,
        }
    result = _runs.get(run_id, {"run_id": run_id, "status": "unknown"})
    return {
        key: result.get(key)
        for key in ["run_id", "status", "phase", "gate_decisions", "scorecards"]
    }


@app.get("/runs/{run_id}/artifacts")
def list_artifacts(run_id: str):
    if os.getenv("AIDLC_EXECUTION") == "temporal":
        return list(get_run_repository().latest_artifacts(run_id))
    return list((_runs.get(run_id) or {}).get("artifacts", {}).keys())


@app.get("/runs/{run_id}/artifacts/{name}")
def get_artifact(run_id: str, name: str):
    if os.getenv("AIDLC_EXECUTION") == "temporal":
        return get_run_repository().latest_artifacts(run_id).get(name, {})
    return (_runs.get(run_id) or {}).get("artifacts", {}).get(name, {})


@app.post("/runs/{run_id}/approve")
def approve_run(run_id: str, payload: dict):
    if os.getenv("AIDLC_EXECUTION") == "temporal":
        from aidlc.distributed.client import approve

        asyncio.run(approve(run_id, payload["approved"], payload["by"]))
        return {"run_id": run_id, "status": "signal_sent"}
    result = resume_run(run_id, payload["approved"], payload["by"])
    _runs[run_id] = result
    return {"run_id": run_id, "status": result.get("status")}
