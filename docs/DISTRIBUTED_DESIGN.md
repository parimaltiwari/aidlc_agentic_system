# AIDLC Distributed Execution Design — Temporal + Postgres Shared History

Status: **Draft for review — design only, no implementation yet.**
Companion to `docs/DESIGN.md` (single-machine architecture).

Contents

1. Goals and non-goals
2. Current state and what changes
3. Target architecture
4. Layering: Temporal above, LangGraph inside
5. Shared history in Postgres (schema)
6. Workflow and activity design
7. Human approval gates as Signals
8. Swarm fan-out and concurrency control
9. Memory model: run, project, organisation
10. Multi-developer / multi-machine topology
11. Failure handling and idempotency
12. Observability
13. Security and tenancy
14. Migration plan (implementation slices)
15. Decisions to confirm
16. Appendix: alternatives considered

---

## 1. Goals and non-goals

**Goals**

- Several developers can each start AIDLC runs; the work (phases and per-work-item
  agent swarms) is executed by a pool of workers on many machines.
- All runs share one **coordinated memory**: state, artifacts, and history live in
  one place and any worker or user can read/resume any run.
- A **common, append-only history**: every agent invocation, artifact version,
  scorecard, gate decision and change request is recorded once, queryable
  across runs and projects.
- Human approval gates may wait for hours or days without holding a process or
  a worker slot.
- Crash of any worker or machine never loses or duplicates a run's progress.
- Keep the existing agents, phase graphs, evaluators, gates and artifact
  schemas unchanged as far as possible.

**Non-goals (this iteration)**

- Real deployment adapters (deploy remains simulation).
- Replacing LangGraph inside phases.
- Multi-region / geo-replication.
- A UI beyond Temporal's Web UI and the existing CLI/API.

---

## 2. Current state and what changes

| Concern | Today (single machine) | Target |
|---|---|---|
| Orchestration across phases | LangGraph master graph, `master.py` | **Temporal workflow** (`AidlcRunWorkflow`) |
| Orchestration inside a phase | LangGraph subgraph | unchanged, executed inside a Temporal **activity** |
| Run state / checkpoints | `SqliteSaver` at `runs/checkpoints.sqlite` | Temporal event history (cross-phase) + **Postgres** LangGraph checkpointer (intra-phase) |
| Artifacts | `runs/<id>/artifacts/*.vN.json` | **Postgres** `artifact_versions` (+ optional S3 for large blobs) |
| Trace | `runs/<id>/trace.jsonl` | **Postgres** `agent_invocations` |
| Human gates | LangGraph `interrupt()` + `Command(resume)` | Temporal **Signal** `approve_gate`, workflow `wait_condition` |
| Retries / backward routing | `_route_update` in `master.py` | same logic, expressed in workflow code |
| Build sandbox | `runs/<id>/sandbox` on local disk | per-activity local scratch; results (diffs, `StaticReport`) persisted to Postgres; sandbox archived to object storage |
| CLI / API | in-process `run_pipeline` | Temporal client: `start_workflow`, `signal`, `query` |

Everything under `aidlc/agents/**`, `aidlc/core/artifacts.py`, `aidlc/core/evals.py`,
`aidlc/core/gate.py` (policy part) and the five phase graphs is retained.

---

## 3. Target architecture

```
 Developers (5+)                         Machines (N workers)
 ┌──────────┐  aidlc run / POST /runs    ┌──────────────────────────┐
 │ CLI/API  │──────────────┐             │ Worker: task queue        │
 └──────────┘              │             │  "aidlc-phases"           │
 ┌──────────┐              ▼             │  activities: run_phase,   │
 │ CLI/API  │────▶ ┌────────────────┐    │  run_work_item, ...       │
 └──────────┘      │ Temporal Server │◀──┤                          │
        ▲          │ (self-hosted)   │    ├──────────────────────────┤
        │ signals  │ + Web UI        │    │ Worker: task queue        │
        │ approve  └────────┬────────┘    │  "aidlc-build" (GPU box)  │
        │                   │             │  activities: coder swarm  │
        │                   │             └──────────────────────────┘
        │                   ▼                        │
        │        ┌──────────────────────┐            │
        └────────│  Postgres (shared    │◀───────────┘
                 │  history)            │   artifacts, invocations,
                 │  - runs              │   scorecards, gates,
                 │  - artifact_versions │   LangGraph checkpoints
                 │  - agent_invocations │
                 │  - scorecards/gates  │
                 │  - langgraph_*       │
                 └──────────────────────┘
                            │
                 ┌──────────┴───────────┐
                 │ Object store (S3/    │  sandboxes, large diffs,
                 │ MinIO) — optional    │  test logs
                 └──────────────────────┘
                            │
                 ┌──────────┴───────────┐
                 │ LLM endpoints        │  Ollama (GPU hosts) /
                 │ (Ollama / LiteLLM)   │  hosted open models
                 └──────────────────────┘
```

Two databases of record, with clear ownership:

- **Temporal** owns *control flow*: which phase is running, retries, back-hops,
  who approved what and when. Its event history is immutable and replayable.
- **Postgres (`aidlc` schema)** owns *content*: artifacts, agent traces,
  scorecards, gate decisions, change requests, and LangGraph intra-phase
  checkpoints. This is the "common history" developers and future agents read.

Temporal's own persistence also uses Postgres; it can share the same server
(separate database/schema) or a dedicated one.

---

## 4. Layering: Temporal above, LangGraph inside

```
AidlcRunWorkflow (Temporal, deterministic)
 ├─ activity run_phase("requirements", run_id)      ← LangGraph requirements graph
 ├─ activity run_phase("design", run_id)            ← LangGraph design graph
 ├─ activity run_phase("build", run_id)             ← scaffold + fan-out (see §8) + static/tests + integrator
 ├─ activity run_phase("test_eval", run_id)
 ├─ activity run_phase("deploy", run_id)
 └─ between phases: evaluate scorecard → gate → wait for approval signal → route
```

Rules:

- **Workflow code** contains only the logic from `master.py` `_route_update` /
  `_next_route` plus gate waiting. It is deterministic: no I/O, no LLM calls, no
  clocks except `workflow.now()`.
- **Activities** do all I/O: load state from Postgres, run the LangGraph phase
  graph, persist artifacts/trace/scorecards, return a small `PhaseResult`.
- Phase graphs keep using LangGraph but with `PostgresSaver` and **no
  `interrupt()`**: the gate node computes the `GateDecision` (auto/review/block)
  and returns; waiting for a human moves up into the workflow (§7).
- Agents (`BaseAgent.run`) are unchanged. `ArtifactStore` and `Tracer` become
  interfaces with a Postgres implementation selected by config.

Why not put each agent in its own activity? Possible later (finer retries,
per-agent routing to GPU workers), but phase-level activities keep the first
slice small and preserve the existing subgraph tests. The Build phase is the
exception (§8) because it is the swarm.

---

## 5. Shared history in Postgres (schema)

All tables are append-only except `runs.status`/`runs.phase`. Every row carries
`run_id`; `project_id` and `org_id` enable cross-run memory. Times are UTC.

```sql
CREATE TABLE projects (
  id            uuid PRIMARY KEY,
  org_id        uuid NOT NULL,
  name          text NOT NULL,
  repo_url      text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
  id            uuid PRIMARY KEY,               -- == Temporal workflow_id
  project_id    uuid NOT NULL REFERENCES projects(id),
  intent        text NOT NULL,
  context       jsonb NOT NULL,                 -- RunContext
  status        text NOT NULL,                  -- running|awaiting_approval|completed|blocked|failed
  phase         text NOT NULL,
  requested_by  text NOT NULL,                  -- developer identity
  parent_run_id uuid REFERENCES runs(id),       -- for re-runs / forks
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE artifact_versions (
  id            bigserial PRIMARY KEY,
  run_id        uuid NOT NULL REFERENCES runs(id),
  key           text NOT NULL,                  -- e.g. requirements_spec, code_diff_WI-2
  version       int  NOT NULL,                  -- 1..n per (run_id,key)
  schema        text NOT NULL,                  -- Pydantic class name
  phase         text NOT NULL,
  agent         text NOT NULL,
  attempt       int  NOT NULL DEFAULT 1,        -- phase retry number
  body          jsonb,                          -- inline when < 1 MB
  blob_uri      text,                           -- s3://... when large
  content_hash  text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, key, version)
);
CREATE INDEX ON artifact_versions (run_id, key, version DESC);
CREATE INDEX ON artifact_versions USING gin (body jsonb_path_ops);

CREATE TABLE agent_invocations (               -- replaces trace.jsonl
  id            bigserial PRIMARY KEY,
  run_id        uuid NOT NULL REFERENCES runs(id),
  phase         text NOT NULL,
  agent         text NOT NULL,
  work_item_id  text,
  attempt       int  NOT NULL,
  worker_id     text NOT NULL,                  -- hostname/pid
  temporal_activity_id text,
  model         text,                           -- e.g. ollama_chat/qwen2.5:7b
  input_keys    text[] NOT NULL,                -- relevant_artifacts actually sent
  output_key    text,
  prompt_tokens int, completion_tokens int, cost_usd numeric(10,4),
  started_at    timestamptz NOT NULL,
  duration_ms   int NOT NULL,
  ok            boolean NOT NULL,
  error         text
);
CREATE INDEX ON agent_invocations (run_id, started_at);

CREATE TABLE scorecards (
  id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
  phase text NOT NULL, attempt int NOT NULL, agent text NOT NULL,
  scores jsonb NOT NULL, overall numeric(4,3) NOT NULL, passed boolean NOT NULL,
  feedback text[] NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gate_decisions (
  id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
  phase text NOT NULL, attempt int NOT NULL,
  decision text NOT NULL,                       -- auto|review|block
  reason text NOT NULL,
  approved boolean, approved_by text, approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE change_requests (
  id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
  cr_id text NOT NULL, source_phase text NOT NULL, target_phase text NOT NULL,
  reason text NOT NULL, details text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run_events (                      -- human-readable log lines
  id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id),
  ts timestamptz NOT NULL DEFAULT now(), level text NOT NULL, message text NOT NULL
);

-- LangGraph PostgresSaver creates its own tables (checkpoints, checkpoint_writes,
-- checkpoint_blobs) in the same database; thread_id = run_id || ':' || phase || ':' || attempt.
```

Views for the "common history" consumers:

- `latest_artifacts(run_id, key) → body` — current version per key.
- `run_timeline(run_id)` — union of invocations, scorecards, gates, CRs ordered by time.
- `project_memory(project_id)` — latest `requirements_spec`, `architecture_decisions`,
  `threat_model`, `triage_report` across completed runs (input to §9).

Retention: artifacts and invocations kept indefinitely (they are the memory);
sandbox blobs in object storage expire after N days.

---

## 6. Workflow and activity design

### 6.1 `AidlcRunWorkflow`

```python
@workflow.defn
class AidlcRunWorkflow:
    def __init__(self):
        self.approvals: dict[str, GateApproval] = {}   # phase:attempt → approval
        self.status = "running"
        self.phase = "requirements"
        self.retries: dict[str, int] = {}
        self.change_requests: list[ChangeRequest] = []

    @workflow.run
    async def run(self, req: StartRun) -> RunSummary:
        phase = "requirements"
        while phase != "end":
            attempt = self.retries.get(phase, 0) + 1
            result: PhaseResult = await workflow.execute_activity(
                run_phase, PhaseInput(req.run_id, phase, attempt, self.change_requests),
                task_queue=queue_for(phase),
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=["AgentValidationError"]),
            )
            decision = await self._gate(phase, attempt, result)
            phase = self._route(phase, result, decision)      # port of master._route_update/_next_route
        return RunSummary(run_id=req.run_id, status=self.status)

    async def _gate(self, phase, attempt, result) -> GateDecision:
        if result.gate.decision == "block":
            return result.gate
        if result.gate.decision == "auto" or req.auto_approve:
            return result.gate
        self.status = "awaiting_approval"
        await workflow.execute_activity(record_status, ...)         # mirror to Postgres runs.status
        key = f"{phase}:{attempt}"
        await workflow.wait_condition(lambda: key in self.approvals,
                                      timeout=timedelta(days=14))
        approval = self.approvals[key]
        self.status = "running"
        return result.gate.with_approval(approval)

    @workflow.signal
    def approve_gate(self, approval: GateApproval):   # phase, attempt, approved, by
        self.approvals[f"{approval.phase}:{approval.attempt}"] = approval

    @workflow.query
    def get_status(self) -> RunStatus: ...
```

Routing rules are exactly those in `docs/DESIGN.md` §3: ≤2 retries per phase,
≤2 backward hops, block → end, deploy approved → completed. A 14-day approval
timeout marks the run `blocked` with reason `approval_timeout`.

### 6.2 Activities

| Activity | Task queue | Does |
|---|---|---|
| `run_phase(PhaseInput) → PhaseResult` | `aidlc-phases` (or `aidlc-build` for build) | Load run + latest artifacts from Postgres → build `AidlcState` → invoke phase LangGraph with `PostgresSaver` → persist new artifacts, invocations, scorecard, gate decision → return `PhaseResult(gate, scorecard_passed, triage_target)` |
| `run_work_item(WorkItemInput) → WorkItemResult` | `aidlc-build` | Coder → unit-test writer → reviewer for one `WI-n` (see §8) |
| `run_static_and_tests(run_id, attempt)` | `aidlc-build` | Materialise sandbox from artifacts, run ruff/pytest, persist `StaticReport` |
| `record_status(run_id, status, phase)` | `aidlc-phases` | Update `runs` row |
| `archive_sandbox(run_id, attempt)` | `aidlc-build` | Tar sandbox → object store, return URI |

Activities **heartbeat** after every agent call so a hung LLM call on a dead
worker is detected and retried elsewhere.

`PhaseResult` is deliberately small (KBs, not the artifacts) — Temporal
payloads should stay under ~2 MB; the content is in Postgres.

---

## 7. Human approval gates as Signals

- `gate_node` in the phase graphs stops calling `interrupt()`; it only records
  the `GateDecision` (auto / review / block) using the unchanged `GatePolicy`.
- The workflow waits with `wait_condition` — no worker, thread or DB connection
  is held while waiting; the workflow is just history in Temporal.
- `aidlc approve <run_id> --by NAME [--reject]` and `POST /runs/{id}/approve`
  send the `approve_gate` Signal via the Temporal client. Approvals are recorded
  twice: in Temporal history (authoritative for control flow) and in
  `gate_decisions` (for the shared history/queries).
- Identity: `by` is taken from the authenticated API user / `AIDLC_USER`, not a
  free-text flag, once auth is in place (§13).
- Optional: Slack/Teams notification activity when a gate enters `review`.

---

## 8. Swarm fan-out and concurrency control

The Build phase is where "swarms" happen. Instead of a single `run_phase("build")`
activity, Build is expressed in the workflow as:

```
scaffold (activity)
  └─ for each topological layer of design_package.work_plan.items:
        await asyncio.gather(*[execute_activity(run_work_item, WI) for WI in layer])
static_and_tests (activity)
integrator (activity)
evaluate + gate (inside integrator activity, or a final small activity)
```

- Items in the same dependency layer run in **parallel across machines**; layers
  run sequentially, preserving `depends_on` semantics from `_ordered_items`.
- `run_work_item` runs the coder → unit-test writer → reviewer LangGraph
  fragment for one item, writes `code_diff_<WI>`, `unit_test_diff_<WI>`,
  `review_report_<WI>` to Postgres, and *does not* touch a shared sandbox.
- `run_static_and_tests` materialises the sandbox **from artifacts** (scaffold
  files + all diffs in topological order) on whichever worker picks it up, so
  no shared filesystem is needed.
- Concurrency limits: Temporal worker `max_concurrent_activities` and per-queue
  worker counts bound LLM load; a `budget_usd` check in `run_work_item` (sum of
  `agent_invocations.cost_usd` for the run) fails the activity with a
  non-retryable `BudgetExceeded`, which the workflow turns into `blocked`.
- Write conflicts: artifact keys are unique per work item, and
  `artifact_versions (run_id,key,version)` is unique — a duplicate activity
  attempt (Temporal at-least-once) inserts the next version or, if
  `content_hash` matches the latest, is a no-op. Readers always take the latest
  version, so retries are idempotent.

Later extension: per-agent activities on separate queues, e.g. `coder` on GPU
workers with a 7B–32B model and `reviewer` on a cheaper queue.

---

## 9. Memory model: run, project, organisation

| Scope | Where | Who reads it |
|---|---|---|
| **Run memory** (working memory) | `AidlcState` rebuilt from `latest_artifacts(run_id)` at the start of every activity; intra-phase LangGraph checkpoints in Postgres | Agents within the run via `relevant_artifacts` |
| **Project memory** | `project_memory` view + `artifact_versions` filtered by `project_id` | `CodebaseAnalystAgent`, `SolutionArchitectAgent`, `RegressionTriageAgent` receive prior ADRs / threat models / triage outcomes as an extra `project_memory` artifact (new optional key) |
| **Organisation memory** | Cross-project queries on `artifact_versions`, `scorecards`, `agent_invocations` | Evaluator calibration, model routing decisions, reporting |
| **Long-term semantic memory** (phase 2) | `pgvector` column on `artifact_versions` (embedding of `body`) | Retrieval of similar past requirements/ADRs/incidents into prompts |

Design rule: agents never query Postgres directly. The activity that hosts them
assembles the state (including any memory artifacts) so agents stay pure
functions of state and remain testable with `MockLLM`.

---

## 10. Multi-developer / multi-machine topology

- **Temporal namespace** `aidlc` (one per org; per-team namespaces optional).
- **Task queues:** `aidlc-phases` (CPU workers, any laptop or VM),
  `aidlc-build` (GPU or high-core boxes running Ollama), optional
  `aidlc-deploy` (workers with deployment credentials).
- **Workers** are `aidlc worker --queues aidlc-phases,aidlc-build`; any
  developer's machine can join or leave the pool at any time — Temporal
  reschedules in-flight activities on heartbeat timeout.
- **Workflow ID = run_id**, with `WorkflowIdReusePolicy.REJECT_DUPLICATE`, so a
  run can never be started twice.
- **Search attributes** (`project_id`, `requested_by`, `phase`, `status`) make
  runs discoverable in the Temporal UI and via `aidlc list`.
- **Configuration** via env: `AIDLC_TEMPORAL_ADDRESS`, `AIDLC_TEMPORAL_NAMESPACE`,
  `AIDLC_DATABASE_URL`, `AIDLC_BLOB_URL` (optional), `OLLAMA_BASE_URL`
  per worker (each GPU box points at its own Ollama).

Local developer mode remains: `temporal server start-dev` + a Docker Postgres +
`aidlc worker` on one laptop reproduces the full stack; `AIDLC_EXECUTION=local`
keeps today's in-process LangGraph path for unit tests.

---

## 11. Failure handling and idempotency

| Failure | Handling |
|---|---|
| Worker crashes mid-phase | Activity heartbeat times out → Temporal retries on another worker; LangGraph `PostgresSaver` lets the phase resume from its last node rather than restarting |
| LLM validation failure after retries | `AgentValidationError` (non-retryable) → phase evaluator fails → workflow retry logic (≤2) → blocked |
| LLM endpoint down | Retryable activity error with exponential backoff (max 3); evaluator's deterministic-only fallback still applies for judges |
| Duplicate activity execution | Artifact writes are version-append with hash de-dup; invocations table tolerates duplicates (they are facts about attempts) |
| Postgres unavailable | Activity fails and retries; workflow history is unaffected |
| Temporal unavailable | CLI/API cannot start or approve runs; running activities finish and results are persisted on reconnect |
| Workflow code change while runs are in flight | Temporal **versioning** (`workflow.patched`) or Worker Versioning build IDs; routing logic changes must be gated |

---

## 12. Observability

- Temporal Web UI: per-run event history, pending activities, waiting gates.
- Postgres `run_timeline` view: the business-level history (which agent produced
  what, how long, cost).
- OpenTelemetry: Temporal SDK interceptors + a span per `BaseAgent.run`
  (agent, model, tokens) exported to any OTLP backend; `agent_invocations`
  remains the durable copy.
- Metrics to watch: gate wait time, phase retry rate, backward-hop rate,
  cost per run, LLM latency per model/queue.

---

## 13. Security and tenancy

- Workers hold LLM and repo credentials; the API/CLI hold only Temporal client
  certs. Deployment credentials only on the `aidlc-deploy` queue.
- Row-level tenancy by `org_id` on `projects`; API enforces project membership
  before `start`/`approve`/`read`.
- Artifacts may contain source code: encrypt Postgres at rest, TLS to Temporal
  and Postgres, mTLS between workers and Temporal.
- Approvals carry authenticated identity; the Temporal history is the audit log.
- Sandboxes run under a per-activity temp dir with no access to the worker's
  own repos; optionally inside a container/`firejail` in a later slice.

---

## 14. Migration plan (implementation slices)

Each slice is independently shippable and keeps the mock test suite green.

| # | Slice | Scope | Verifies |
|---|---|---|---|
| 1 | **Storage interfaces + Postgres backends** | `ArtifactStore`/`Tracer` become protocols; add `PostgresArtifactStore`, `PostgresTracer`, `runs`/`scorecards`/`gate_decisions`/`change_requests` writers; Alembic migrations; `AIDLC_DATABASE_URL` switch; keep file backend as default | existing 9 tests + new store tests against a Docker Postgres |
| 2 | **LangGraph PostgresSaver** | replace `SqliteSaver` when `AIDLC_DATABASE_URL` set; thread id scheme `run:phase:attempt` | approval/resume test on Postgres |
| 3 | **Temporal workflow + phase activities** | `aidlc/distributed/{workflow,activities,worker}.py`; `run_phase`; gate waiting via Signals; `aidlc worker`; CLI/API switch to Temporal client when `AIDLC_EXECUTION=temporal` | Temporal Python SDK time-skipping test env: full mock run, block, retry, backward hop, approve/reject |
| 4 | **Build swarm** | `run_work_item` per WI, layered `gather`, sandbox materialisation from artifacts, budget guard | parallel WIs on two local workers |
| 5 | **Project memory** | `project_memory` view + optional `project_memory` artifact into design/triage agents | design agents receive prior ADRs in prompts |
| 6 | **Ops** | docker-compose (Temporal, Postgres, MinIO, Ollama), OTel, search attributes, `aidlc list` | end-to-end on two machines |

Estimated effort: slices 1–3 ≈ one session; 4–6 ≈ one more session, excluding
external waits (Postgres/Temporal hosts, GPU machines).

---

## 15. Decisions to confirm

1. **Self-hosted Temporal vs Temporal Cloud** — design assumes self-hosted
   (open source, MIT); Cloud is a drop-in if preferred.
2. **Object storage** — inline JSONB only (simplest) vs MinIO/S3 for sandboxes
   and large diffs from day one. Recommendation: inline first, blob URI column
   reserved (already in schema).
3. **Activity granularity** — phase-level (recommended for slice 3) vs
   agent-level from the start.
4. **Postgres for Temporal's own persistence** — share the same server (one
   fewer component) or dedicated instance.
5. **Auth for approvals** — API key per developer now, OIDC later?
6. **pgvector** in scope for slice 5 or deferred.

---

## 16. Appendix: alternatives considered

- **Celery + Redis**: simplest to run, but no durable long waits for approvals,
  no replayable history, crash recovery left to application code. Fine for
  single-team, single-box parallelism; not for the stated multi-machine,
  human-gated requirement.
- **LangGraph Platform / self-hosted LangGraph Server**: keeps one framework,
  but distributed multi-worker execution and long-running interrupts are less
  mature in the open-source server than in Temporal, and it couples the
  cross-phase control plane to the LLM framework.
- **Ray**: excellent for compute swarms, weak on durable workflows/approvals;
  could later back the `aidlc-build` queue if scale demands it.
- **Kafka/NATS event choreography**: maximal decoupling but routing/retry/back-hop
  logic would be smeared across consumers; harder to reason about than one
  workflow definition.
