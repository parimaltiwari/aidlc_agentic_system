# AIDLC build and operations guide

This guide is for a development team receiving the repository. It describes
the architecture that is implemented in slices 1–3 and the acceptance bar for
the planned slices.

## Architecture in one page

Temporal owns cross-phase durable orchestration and long-lived approval waits.
Its `AidlcRunWorkflow` invokes phase-level activities. Each activity loads shared
state from the run repository and invokes one LangGraph phase subgraph. The
subgraph runs specialist agents, evaluators, and gates; agents use the mock
provider by default or LiteLLM for a model gateway. Postgres stores shared
history and LangGraph checkpoints when `AIDLC_DATABASE_URL` is configured.

```text
CLI / FastAPI
     │ start / query / approve
     ▼
Temporal workflow: AidlcRunWorkflow
     │ phase activity + approval Signal
     ▼
LangGraph phase subgraph
     │
     ├── agents ──► MockLLM (default) / LiteLLM / Ollama
     ├── evaluator + gate
     └── sandbox tools
     │
     └──────────────► Postgres shared history
                      runs, artifacts, traces, scorecards,
                      gates, change requests, checkpoints

Optional MinIO/S3: sandbox archives and large diffs (slice 4)
```

In local mode, the same phase graphs run in-process, file artifacts/traces are
used, and SQLite checkpoints are selected. This default is the path covered by
the basic mock tests.

## Decisions taken

These resolve §17 of [`DISTRIBUTED_DESIGN.md`](DISTRIBUTED_DESIGN.md):

1. **Self-hosted Temporal via Docker Compose**; Temporal Cloud is a later swap —
   the current worker/client contract already isolates the server endpoint.
2. **Inline JSONB now**; MinIO/S3 is for sandbox archives and large diffs in
   slice 4 — current artifacts fit the relational history path.
3. **Phase-level activities now**; per-work-item activities arrive in slice 4 —
   this preserves the existing phase subgraphs while making phases durable.
4. **One Postgres server, separate `aidlc` and `temporal` databases** — AIDLC
   history and Temporal persistence have clear ownership boundaries.
5. **Approvals carry `--by` identity**; API-key-per-developer on FastAPI is slice
   6 and OIDC is later — the current CLI/API already record approver identity.
6. **Defer pgvector**; slice 5 starts with relational project memory — it keeps
   the first memory implementation queryable without another extension.
7. **vLLM is the default model server**, with TGI as an alternative behind the
   same LiteLLM proxy — agents remain provider/model agnostic.
8. **Apache-2.0/MIT models only by default** (Qwen2.5, DeepSeek); a
   Llama-licensed judge requires legal sign-off — this keeps the default model
   catalogue permissive.
9. **Start with two GPUs minimum** (coder 32B AWQ plus fast 7B), then grow to
   one replica per tier — this separates coding quality from fast orchestration.

## Implemented interfaces

### Storage protocols

The exact contracts in [`aidlc/storage/protocols.py`](../aidlc/storage/protocols.py)
are:

```python
class ArtifactStoreProtocol(Protocol):
    def save(self, name: str, value: Any) -> str: ...
    def list(self) -> list[str]: ...
    def read(self, name: str) -> Any: ...
    def latest_all(self) -> dict[str, Any]: ...

class TracerProtocol(Protocol):
    def record(
        self,
        agent: str,
        phase: str,
        duration: float,
        ok: bool,
        error: str | None = None,
        *,
        model: str | None = None,
        work_item_id: str | None = None,
        attempt: int = 1,
    ) -> None: ...

class RunRepository(Protocol):
    def upsert_run(
        self,
        run_id: str,
        intent: str,
        context: dict,
        status: str,
        phase: str,
        requested_by: str,
    ) -> None: ...
    def update_status(self, run_id: str, status: str, phase: str) -> None: ...
    def add_scorecard(
        self,
        run_id: str,
        phase: str,
        attempt: int,
        scorecard_dict: dict,
    ) -> None: ...
    def add_gate_decision(
        self,
        run_id: str,
        phase: str,
        attempt: int,
        decision_dict: dict,
        approval_by: str | None = None,
    ) -> None: ...
    def add_change_request(self, run_id: str, cr_dict: dict) -> None: ...
    def add_event(self, run_id: str, level: str, message: str) -> None: ...
    def get_run(self, run_id: str) -> dict | None: ...
    def latest_artifacts(self, run_id: str) -> dict[str, Any]: ...
```

File implementations live in [`aidlc/storage/files.py`](../aidlc/storage/files.py);
Postgres implementations live in
[`aidlc/storage/postgres.py`](../aidlc/storage/postgres.py). The factory selects
Postgres only when `AIDLC_DATABASE_URL` is set.

### Temporal payloads and workflow API

The exact dataclasses in [`aidlc/distributed/models.py`](../aidlc/distributed/models.py)
are:

```python
@dataclass
class StartRun:
    run_id: str
    intent: str
    context: dict
    requested_by: str
    auto_approve: bool

@dataclass
class PhaseInput:
    run_id: str
    phase: str
    attempt: int
    change_requests: list[dict] = field(default_factory=list)
    auto_approve: bool = False

@dataclass
class PhaseResult:
    phase: str
    attempt: int
    gate: dict
    scorecard_passed: bool
    status: str
    triage_target: str | None = None

@dataclass
class GateApproval:
    phase: str
    attempt: int
    approved: bool
    by: str

@dataclass
class RunStatus:
    run_id: str
    status: str
    phase: str
    awaiting_gate: str | None = None
```

`AidlcRunWorkflow` exposes the Signal `approve_gate` and Query `get_status`.
The client helpers are `start_run`, `approve`, and `status` in
[`aidlc/distributed/client.py`](../aidlc/distributed/client.py).

### Environment variables

| Variable | Current behavior |
|---|---|
| `AIDLC_DATABASE_URL` | Selects Postgres history and Postgres LangGraph checkpoints; unset selects files and SQLite. |
| `AIDLC_EXECUTION` | `temporal` selects the Temporal client path; unset selects in-process execution. |
| `AIDLC_TEMPORAL_ADDRESS` | Temporal endpoint; defaults to `localhost:7233`. |
| `AIDLC_TEMPORAL_NAMESPACE` | Temporal namespace; defaults to `default`. |
| `AIDLC_LLM_PROVIDER` | `mock` by default; `litellm` and `ollama` are also supported. |
| `AIDLC_MODEL` | Fast-agent model setting. |
| `AIDLC_MODEL_STRONG` | Strong/evaluator model setting. |
| `AIDLC_AUTO_APPROVE` | `1` bypasses review gates. |
| `AIDLC_RUNS_DIR` | File artifacts, traces, sandboxes, and SQLite checkpoints; defaults to `./runs`. |

## Local stack recipe

The following recipe was executed successfully on this checkout with mock LLM
calls. The Compose stack creates Postgres databases `aidlc` and `temporal`,
Temporal on port 7233, and the Temporal UI on port 8080.

```bash
docker compose -f deploy/docker-compose.yml up -d

AIDLC_DATABASE_URL=postgresql://aidlc:aidlc@127.0.0.1:5432/aidlc \
  uv run aidlc worker --address 127.0.0.1:7233 --namespace default

AIDLC_DATABASE_URL=postgresql://aidlc:aidlc@127.0.0.1:5432/aidlc \
AIDLC_EXECUTION=temporal \
AIDLC_TEMPORAL_ADDRESS=127.0.0.1:7233 \
AIDLC_TEMPORAL_NAMESPACE=default \
AIDLC_LLM_PROVIDER=mock \
  uv run aidlc run "add health endpoint" --risk high --execution temporal
```

The run returned `54ffbac4-48dc-405a-8524-3f761f1222cc` and reached
`awaiting_approval` at `requirements:1`. Approve each gate with:

```bash
AIDLC_EXECUTION=temporal \
AIDLC_TEMPORAL_ADDRESS=127.0.0.1:7233 \
AIDLC_TEMPORAL_NAMESPACE=default \
  uv run aidlc approve 54ffbac4-48dc-405a-8524-3f761f1222cc --by dev --execution temporal

AIDLC_EXECUTION=temporal \
AIDLC_TEMPORAL_ADDRESS=127.0.0.1:7233 \
AIDLC_TEMPORAL_NAMESPACE=default \
  uv run aidlc status 54ffbac4-48dc-405a-8524-3f761f1222cc --execution temporal
```

The verified status sequence was `requirements → design → build → test_eval →
deploy → completed`. A direct Postgres query confirmed one `runs` row, 29
`artifact_versions` rows, and five `gate_decisions` rows for the run:

```bash
docker exec deploy-postgres-1 psql -U aidlc -d aidlc -c \
  "SELECT 'runs' AS table_name, count(*) FROM runs WHERE id='54ffbac4-48dc-405a-8524-3f761f1222cc' UNION ALL SELECT 'artifact_versions', count(*) FROM artifact_versions WHERE run_id='54ffbac4-48dc-405a-8524-3f761f1222cc' UNION ALL SELECT 'gate_decisions', count(*) FROM gate_decisions WHERE run_id='54ffbac4-48dc-405a-8524-3f761f1222cc';"
```

Tear down the local stack when finished:

```bash
docker compose -f deploy/docker-compose.yml down -v
```

For the complete test suite, including Postgres integration tests:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
AIDLC_TEST_DATABASE_URL=postgresql://aidlc:aidlc@127.0.0.1:55432/aidlc \
  uv run pytest -q
```

The last command requires a Postgres test instance on port 55432. Temporal
tests use the in-process time-skipping environment and the mock provider.

## Slice 4–7 acceptance criteria

### Slice 4 — distributed build swarm

- N work items from `WorkPlan` run as parallel activities on the `aidlc-build`
  queue, with dependency-aware scheduling and a per-run budget guard test.
- A build activity can reconstruct its sandbox solely from persisted artifacts on
  a different machine; no user-repository writes occur outside that sandbox.
- Sandbox archives, large diffs, and test logs use the optional MinIO/S3 path.
- Retry, cancellation, idempotency, and partial-failure tests cover one work item
  without duplicating its artifact version.

### Slice 5 — relational project memory

- A completed run contributes project memory records that are visible to Design
  and Test/Eval triage agents on a later run.
- Memory retrieval is scoped by project and does not require pgvector.
- A test proves a later design prompt includes a relevant prior ADR or triage
  record and that absent memory is handled deterministically.

### Slice 6 — team operations and observability

- OpenTelemetry traces cover workflow, activity, agent, and tool spans.
- `aidlc list` shows runs and approval state from shared history.
- API-key-per-developer authentication covers FastAPI run, status, artifact, and
  approval endpoints.
- Two machines can run separate workers against the Compose stack and complete
  one end-to-end mock run.
- The cluster topology, scaling signals, backup/retention, and incident
  runbooks meet [`OPERATIONS.md`](OPERATIONS.md).
- Bearer-key identity, project-scoped roles, secret handling, sandbox controls,
  and the STRIDE-lite checklist meet [`SECURITY.md`](SECURITY.md).

### Slice 7 — model routing and serving

- `coder` and `reasoning` tiers are selectable, with per-agent overrides through
  `AIDLC_MODEL__<agent>`.
- The model used is logged for every invocation and queryable in Postgres.
- A LiteLLM proxy configuration demonstrates aliases and fallbacks.
- A vLLM Helm values example documents the coder 32B AWQ and fast 7B tiers.
- TGI can be substituted behind the same LiteLLM contract.

## Non-functional targets

These are targets for the planned operating point, not measurements of this
checkout:

- Mock run under 30 seconds.
- GPU-hosted real run under 15 minutes for a small feature.
- At least 20 concurrent runs per worker pool.
- Approval waits up to 14 days.
- Every artifact version and agent invocation queryable in Postgres.
- Zero user-repository writes outside the sandbox.

## Definition of done for each slice

Each slice is done when its focused tests and integration tests pass, Ruff check
and formatting pass, the relevant operating and architecture docs are updated,
and the status table in [`DISTRIBUTED_DESIGN.md`](DISTRIBUTED_DESIGN.md) is
updated from Planned to Done. A slice must leave the local mock/file/in-process
default working.
