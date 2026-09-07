"""FastAPI run service."""

import threading
import uuid
from typing import Any

from fastapi import FastAPI
from aidlc.orchestrators.master import resume_run, run_pipeline

app = FastAPI(title="AIDLC API")
_runs: dict[str, dict[str, Any]] = {}


def _run(run_id: str, intent: str, context: dict):
    result = run_pipeline(intent, context, run_id=run_id)
    _runs[run_id] = result


@app.post("/runs")
def create_run(payload: dict):
    run_id = str(uuid.uuid4())
    context = payload.get("context", {"risk_level": "low", "target_env": "simulation"})
    _runs[run_id] = {"run_id": run_id, "status": "running", "phase": "requirements"}
    threading.Thread(target=_run, args=(run_id, payload["intent"], context), daemon=True).start()
    return {"run_id": run_id}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    result = _runs.get(run_id, {"run_id": run_id, "status": "unknown"})
    return {
        key: result.get(key)
        for key in ["run_id", "status", "phase", "gate_decisions", "scorecards"]
    }


@app.get("/runs/{run_id}/artifacts")
def list_artifacts(run_id: str):
    return list((_runs.get(run_id) or {}).get("artifacts", {}).keys())


@app.get("/runs/{run_id}/artifacts/{name}")
def get_artifact(run_id: str, name: str):
    return (_runs.get(run_id) or {}).get("artifacts", {}).get(name, {})


@app.post("/runs/{run_id}/approve")
def approve_run(run_id: str, payload: dict):
    result = resume_run(run_id, payload["approved"], payload["by"])
    _runs[run_id] = result
    return {"run_id": run_id, "status": result.get("status")}
