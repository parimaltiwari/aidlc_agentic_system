"""Typer command-line interface."""

import os
import json
import time
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from aidlc.core.store import ArtifactStore
from aidlc.orchestrators.master import resume_run, run_pipeline

app = typer.Typer(help="AIDLC multi-agent development lifecycle")
console = Console()


@app.command()
def run(
    intent: str,
    repo: str | None = typer.Option(None),
    risk: str = typer.Option("low"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
    provider: str = typer.Option("mock"),
    verbose: bool = typer.Option(False, "--verbose"),
):
    os.environ["AIDLC_LLM_PROVIDER"] = provider
    if auto_approve:
        os.environ["AIDLC_AUTO_APPROVE"] = "1"
    started = time.perf_counter()
    result = run_pipeline(
        intent,
        {
            "repo_path": repo,
            "target_env": "simulation",
            "risk_level": risk,
            "budget_usd": 25.0,
            "stakeholders": [],
        },
    )
    table = Table(title=f"AIDLC run {result['run_id']}")
    table.add_column("Phase")
    table.add_column("Decision")
    table.add_column("Score")
    decisions = {d["phase"]: d for d in result.get("gate_decisions", [])}
    scores = {s["phase"]: s for s in result.get("scorecards", [])}
    for phase in ["requirements", "design", "build", "test_eval", "deploy"]:
        table.add_row(
            phase,
            decisions.get(phase, {}).get("decision", "-"),
            str(scores.get(phase, {}).get("overall", "-")),
        )
    console.print(table)
    console.print(f"Status: {result.get('status')}")
    console.print(
        f"Artifacts: {Path(os.getenv('AIDLC_RUNS_DIR', './runs')) / result['run_id'] / 'artifacts'}"
    )
    if verbose:
        trace_path = Path(os.getenv("AIDLC_RUNS_DIR", "./runs")) / result["run_id"] / "trace.jsonl"
        console.print(f"Wall time: {time.perf_counter() - started:.2f}s")
        console.print("Agent durations:")
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                console.print(
                    f"  {entry['phase']}/{entry['agent']}: "
                    f"{entry['duration_ms']:.2f} ms ({'ok' if entry['ok'] else 'failed'})"
                )


@app.command()
def show(run_id: str):
    store = ArtifactStore(run_id)
    for artifact in store.list():
        console.print(artifact)


@app.command()
def approve(
    run_id: str,
    by: str = typer.Option(..., "--by"),
    reject: bool = typer.Option(False, "--reject"),
):
    result = resume_run(run_id, not reject, by)
    console.print(f"Run {run_id} resumed: {result.get('status')}")


@app.command()
def serve():
    uvicorn.run("aidlc.services.api:app", host="127.0.0.1", port=8000)
