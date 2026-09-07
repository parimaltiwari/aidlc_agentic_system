# AIDLC Distributed Execution Design — Temporal + Postgres Shared History

Status: **Slices 1–3 implemented; slices 4–7 planned.**
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
14. Model serving: hosting open-source models in the enterprise
15. Model-to-agent assignment matrix
16. Migration plan (implementation slices)
17. Decisions to confirm
18. Appendix: alternatives considered

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

| Concern | Current implementation | Target |
|---|---|---|
| Orchestration across phases | **Implemented:** Temporal workflow (`AidlcRunWorkflow`) in `aidlc/distributed/workflow.py`; local LangGraph master remains the default | Per-work-item distributed build orchestration |
| Orchestration inside a phase | **Implemented:** LangGraph subgraph executed inside `run_phase` activity | Per-agent/per-work-item activities |
| Run state / checkpoints | **Implemented:** Temporal event history; local master selects `PostgresSaver` when `AIDLC_DATABASE_URL` is set and SQLite remains the default. Temporal phase activities currently invoke phase graphs without a phase checkpointer. | Cross-machine build checkpoint policy |
| Artifacts | **Implemented:** Postgres `artifact_versions` when configured; file artifacts by default | MinIO/S3 for large blobs and archives |
| Trace | **Implemented:** Postgres `agent_invocations` when configured; JSONL by default | OpenTelemetry spans and metrics |
| Human gates | **Implemented:** Temporal `approve_gate` Signal and `wait_condition` in distributed mode; LangGraph `interrupt()` locally | Approval broker and identity controls |
| Retries / backward routing | **Implemented:** workflow mirrors master retries and triage routing, including two retry and two backward-hop limits | Distributed build fan-out |
| Build sandbox | **Implemented:** activity-local `runs/<id>/sandbox` and persisted artifacts | Portable sandbox reconstruction and archives |
| CLI / API | **Implemented:** Temporal client `start_workflow`, Signal, Query, `aidlc worker`, `--execution temporal`, and `aidlc status` | Team listing, authentication, and OTel |

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
- Phase graphs keep using LangGraph. Temporal activities invoke them without a
  phase checkpointer and set gate record mode, so the gate node computes the
  `GateDecision` (auto/review/block) and returns; waiting for a human moves up
  into the workflow (§7). The local master uses its configured checkpointer.
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
  id            text PRIMARY KEY,
  org_id        text NOT NULL,
  name          text NOT NULL,
  repo_url      text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
  id            text PRIMARY KEY,               -- == Temporal workflow_id
  project_id    text NOT NULL REFERENCES projects(id),
  intent        text NOT NULL,
  context       jsonb NOT NULL,                 -- RunContext
  status        text NOT NULL,                  -- running|awaiting_approval|completed|blocked|failed
  phase         text NOT NULL,
  requested_by  text NOT NULL,                  -- developer identity
  parent_run_id text REFERENCES runs(id),       -- for re-runs / forks
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE artifact_versions (
  id            bigserial PRIMARY KEY,
  run_id        text NOT NULL REFERENCES runs(id),
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
  run_id        text NOT NULL REFERENCES runs(id),
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
  id bigserial PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id),
  phase text NOT NULL, attempt int NOT NULL, agent text NOT NULL,
  scores jsonb NOT NULL, overall numeric(4,3) NOT NULL, passed boolean NOT NULL,
  feedback text[] NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gate_decisions (
  id bigserial PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id),
  phase text NOT NULL, attempt int NOT NULL,
  decision text NOT NULL,                       -- auto|review|block
  reason text NOT NULL,
  approved boolean, approved_by text, approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE change_requests (
  id bigserial PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id),
  cr_id text NOT NULL, source_phase text NOT NULL, target_phase text NOT NULL,
  reason text NOT NULL, details text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run_events (                      -- human-readable log lines
  id bigserial PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id),
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
| `run_phase(PhaseInput) → PhaseResult` | `aidlc-phases` | Load run + latest artifacts from the selected repository → build `AidlcState` → invoke the phase LangGraph without a phase checkpointer → persist new artifacts, invocations, scorecard, gate decision → return `PhaseResult(gate, scorecard_passed, triage_target)` |
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
| Worker crashes mid-phase | Activity heartbeat times out → Temporal retries on another worker; the current phase activity reloads persisted artifacts and reruns its phase graph |
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

The settled controls and implementation checklist are maintained in
[`docs/SECURITY.md`](SECURITY.md).

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

## 14. Model serving: hosting open-source models in the enterprise

Laptop Ollama is fine for development; production swarms need an in-house
inference fleet. The AIDLC code needs no change: every agent already calls
`get_llm(tier).structured(...)`, which resolves to a LiteLLM model string, so
switching to a hosted fleet is configuration.

### 14.1 Serving stack

```
  workers ──▶ LiteLLM Proxy (router, auth, budgets, cost log, fallbacks)
                 │            │             │              │
                 ▼            ▼             ▼              ▼
           vLLM: coder    vLLM: strong   vLLM/TGI: fast   vLLM: embed
           Qwen2.5-Coder  Qwen2.5-72B    Qwen2.5-7B /     bge-m3 /
           -32B (FP8)     or Llama-3.3   Mistral-Small    nomic-embed
           2×H100         -70B  4×H100   1×L40S/A10       1×A10
                 └────────────┴─────────────┴──────────────┘
                     models pulled from HF Enterprise Hub /
                     private S3 mirror; GPUs on K8s (KServe/Helm)
```

| Component | Choice | Why |
|---|---|---|
| Inference engine | **vLLM** (Apache-2.0) as default; **HF TGI** where the HF Hub/Inference Endpoints tooling is already standard | Continuous batching, tensor parallel, prefix caching, OpenAI-compatible API, **guided JSON-schema decoding** (`response_format=json_schema` / `guided_json`) which removes most of our validation retries |
| Router / gateway | **LiteLLM Proxy** (MIT) | One endpoint for all workers; per-team keys and `budget_usd`; model aliases (`aidlc-coder`, `aidlc-strong`, `aidlc-fast`); automatic fallbacks; cost/token logging to Postgres (`agent_invocations.cost_usd`) |
| Model registry | **Hugging Face Enterprise Hub** (private org, gated repos, audit) or a private S3/MinIO mirror | Versioned weights, provenance, license tracking |
| Platform | Kubernetes with GPU operator; Helm charts for vLLM/TGI; KServe or Ray Serve for autoscaling | Scale-to-N replicas per model; canary new model versions |
| Observability | vLLM/TGI Prometheus metrics + LiteLLM logs + OTel spans from `BaseAgent.run` | Latency, queue depth, tokens/s, cost per run |
| Embeddings | vLLM/TEI serving `bge-m3` or `nomic-embed-text` | Feeds the pgvector project memory (§9) |

### 14.2 Model catalogue (open weights, permissive licenses)

| Role / tier | Primary | Alternatives | Hardware (FP8/AWQ) | License |
|---|---|---|---|---|
| `coder` | **Qwen2.5-Coder-32B-Instruct** | DeepSeek-Coder-V2-Lite (16B MoE), Codestral-22B (MNPL — check), Qwen2.5-Coder-7B (cheap) | 2×80GB / 1×80GB (AWQ) | Apache-2.0 |
| `strong` (architecture, judges) | **Qwen2.5-72B-Instruct** | Llama-3.3-70B-Instruct (Llama license), DeepSeek-V3 (MoE, 8×H100), Mistral-Large (research-only — avoid) | 4×80GB | Qwen: Apache-2.0 |
| `fast` (intake, clarifier, notes, summaries) | **Qwen2.5-7B-Instruct** | Mistral-Small-24B (Apache-2.0), Llama-3.1-8B, Gemma-2-9B | 1×24–48GB | Apache-2.0 |
| `reasoning` (triage, threat model, optional) | **DeepSeek-R1-Distill-Qwen-32B** | QwQ-32B | 2×80GB | MIT / Apache-2.0 |
| `embed` | **bge-m3** | nomic-embed-text-v1.5, e5-mistral-7b | 1×24GB | MIT / Apache-2.0 |

Rule: prefer Apache-2.0/MIT weights; record license per model in the registry;
Llama-licensed models are acceptable for internal use but flag them.

### 14.3 Configuration

```bash
AIDLC_LLM_PROVIDER=litellm
OPENAI_API_BASE=https://llm-gateway.corp.example/v1      # LiteLLM proxy
OPENAI_API_KEY=<team key issued by the proxy>
AIDLC_MODEL=aidlc-fast            # proxy aliases → vLLM deployments
AIDLC_MODEL_STRONG=aidlc-strong
AIDLC_MODEL_CODER=aidlc-coder     # new tier, see §15
AIDLC_MODEL_REASONING=aidlc-reasoning
```

The proxy config maps each alias to a primary deployment and an ordered
fallback list (e.g. `aidlc-coder → [vllm/qwen2.5-coder-32b, vllm/qwen2.5-coder-7b]`),
so a GPU outage degrades quality rather than failing the run; the evaluator's
deterministic checks still guard the result.

### 14.4 Sizing guidance

- One `run_work_item` ≈ 3 agent calls of 1–3k output tokens. On 2×H100 vLLM,
  Qwen2.5-Coder-32B sustains ~40–60 concurrent sequences at ~30 tok/s each →
  roughly 5–10 parallel work items comfortably per replica.
- Judges are few but long-context; one 72B replica serves several concurrent runs.
- Start: 1 coder replica, 1 strong replica, 1 fast replica (≈ 7 GPUs); scale the
  coder pool first as swarms grow.

---

## 15. Model-to-agent assignment matrix

Robustness comes from matching model capability to each sub-agent's job and
from having a declared fallback per agent, rather than one model for all. Tiers
are resolved through `get_llm(tier)`; we add `coder` and `reasoning` to the
existing `fast`/`strong`.

| Phase | Agent | Tier | Primary model | Fallback | Rationale |
|---|---|---|---|---|---|
| Req | IntakeContextAgent | fast | Qwen2.5-7B | Mistral-Small-24B | Summarisation; cheap |
| Req | StakeholderClarifierAgent | fast | Qwen2.5-7B | Mistral-Small-24B | Question generation |
| Req | RequirementsAuthorAgent | strong | Qwen2.5-72B | Llama-3.3-70B | Quality of REQs drives everything downstream |
| Req | DomainComplianceAgent | strong | Qwen2.5-72B | Llama-3.3-70B | Regulatory nuance |
| Req | FeasibilityScopeAgent | fast | Qwen2.5-7B | Qwen2.5-72B | Estimates; low risk |
| Req | RequirementsEvaluator (judge) | strong | Qwen2.5-72B | DeepSeek-R1-Distill-32B | Judge must be stronger than author; use a *different* model family where possible to reduce shared bias |
| Design | CodebaseAnalystAgent | coder | Qwen2.5-Coder-32B | Qwen2.5-Coder-7B | Reads code |
| Design | SolutionArchitectAgent | strong | Qwen2.5-72B | Llama-3.3-70B | Trade-off reasoning |
| Design | APIDataModelerAgent | coder | Qwen2.5-Coder-32B | Qwen2.5-72B | Schema precision |
| Design | DataModelerAgent | coder | Qwen2.5-Coder-32B | Qwen2.5-72B | Schema precision |
| Design | ThreatModelAgent | reasoning | DeepSeek-R1-Distill-32B | Qwen2.5-72B | Adversarial thinking |
| Design | TaskDecomposerAgent | strong | Qwen2.5-72B | Qwen2.5-Coder-32B | Dependency ordering, coverage |
| Design | DesignEvaluator (judge) | strong | Llama-3.3-70B | Qwen2.5-72B | Cross-family judge |
| Build | CoderAgent | coder | Qwen2.5-Coder-32B | DeepSeek-Coder-V2-Lite | Code generation |
| Build | UnitTestWriterAgent | coder | Qwen2.5-Coder-32B | Qwen2.5-Coder-7B | Test generation |
| Build | CodeReviewerAgent | strong or coder | Qwen2.5-72B | Qwen2.5-Coder-32B | Reviewer ≠ coder model to avoid self-approval bias |
| Build | IntegratorAgent | fast | Qwen2.5-7B | — | PR text only |
| Build | BuildEvaluator (judge) | strong | Llama-3.3-70B | Qwen2.5-72B | Deterministic checks dominate; judge is secondary |
| Test | TestPlannerAgent | strong | Qwen2.5-72B | Qwen2.5-Coder-32B | Coverage reasoning |
| Test | Integration/E2E/Perf/Security test agents | coder | Qwen2.5-Coder-32B | Qwen2.5-Coder-7B | Test code / assertions |
| Test | RegressionTriageAgent | reasoning | DeepSeek-R1-Distill-32B | Qwen2.5-72B | Root-cause classification drives backward routing |
| Test | QualityAgent | fast | Qwen2.5-7B | — | Prose summary only; `go` is computed |
| Test | TestEvalEvaluator (judge) | strong | Llama-3.3-70B | Qwen2.5-72B | Cross-family judge |
| Deploy | ReleaseManagerAgent | fast | Qwen2.5-7B | Mistral-Small-24B | Release notes |
| Deploy | IaCConfigAgent | coder | Qwen2.5-Coder-32B | Qwen2.5-72B | IaC syntax |
| Deploy | DeploymentExecutor / Observability / Rollback | fast | Qwen2.5-7B | Qwen2.5-72B | Mostly deterministic in future; low LLM load |
| Deploy | DeployEvaluator (judge) | strong | Qwen2.5-72B | Llama-3.3-70B | Health evidence |

Design rules encoded by the matrix:

1. **Separation of duties** — the judge/reviewer for a phase uses a different
   model (ideally family) from the producer, so a model's blind spots are less
   likely to be shared by its critic.
2. **Spend where it compounds** — requirements authoring, architecture and task
   decomposition get the strongest model because errors there multiply
   downstream; leaf agents (notes, summaries) use the cheapest.
3. **Declared fallbacks** — every agent has a fallback of lower cost/size;
   the LiteLLM proxy applies it on outage or rate limit, and
   `agent_invocations.model` records what actually ran.
4. **Deterministic checks are the floor** — evaluators' code checks pass/fail
   regardless of which judge model answered, so a weaker fallback judge can
   lower a score but cannot approve a broken build.
5. **Per-agent overrides** — `AIDLC_MODEL__<agent-name>` (e.g.
   `AIDLC_MODEL__coder=aidlc-coder-large`) lets a team pin a model for one
   agent without touching tiers; resolved in `get_llm(tier, agent=...)`.
6. **Routing by risk** — `RunContext.risk=high` upgrades all `fast` agents to
   `strong` and enables the reasoning tier for triage/threat modelling;
   `low` keeps costs minimal.
7. **Evaluate the matrix, not just the code** — record per-agent scorecards by
   model in Postgres; a monthly report (org memory, §9) shows which model
   assignments yield the best pass rates per agent, and the matrix is tuned
   from data.

Implementation impact (small): extend `get_llm` with `coder`/`reasoning` tiers,
per-agent env overrides and risk-based upgrade; add `tier` to the agents listed
above (currently most default to `fast`); log `model` per invocation.

---

## 16. Migration plan (implementation slices)

Each slice is independently shippable and keeps the mock test suite green.

| # | Slice | Status | Scope | Verifies |
|---|---|---|---|
| 1 | **Storage interfaces + Postgres backends** | Done | Protocols, file/Postgres backends, migrations, `AIDLC_DATABASE_URL` selection, file default | Existing mock tests plus Docker Postgres integration tests |
| 2 | **LangGraph PostgresSaver** | Done | Postgres checkpointer when configured; SQLite default | Approval/resume test on Postgres |
| 3 | **Temporal workflow + phase activities** | Done | Temporal workflow, activities, Signals, worker, CLI/API switch, status query | Time-skipping tests plus verified Compose e2e |
| 4 | **Build swarm** | Planned | `run_work_item` per WI, layered fan-out, portable sandbox, budget guard | Parallel WIs on two workers |
| 5 | **Project memory** | Planned | Project-memory view and design/triage inputs | Later design prompts receive prior ADRs |
| 6 | **Ops** | Planned | OTel, search attributes, `aidlc list`, authentication, multi-machine operation | End-to-end on two machines |
| 7 | **Model routing** | Planned | `coder`/`reasoning` tiers, overrides, proxy aliases/fallbacks, vLLM values | Mock tests plus gateway run |

Estimated effort: slices 1–3 ≈ one session; 4–7 ≈ one more session, excluding
external waits (Postgres/Temporal hosts, GPU machines, model downloads).

---

## 17. Decisions (resolved — see BUILD_GUIDE)

1. Self-hosted Temporal via Docker Compose; Temporal Cloud is a later swap.
2. Inline JSONB now; MinIO/S3 is for sandbox archives and large diffs in slice 4.
3. Phase-level activities now; per-work-item activities are slice 4.
4. One Postgres server with separate `aidlc` and `temporal` databases.
5. Approvals carry `--by`; FastAPI API keys are slice 6 and OIDC is later.
6. pgvector is deferred; slice 5 starts with relational project memory.
7. vLLM is the default; TGI is an alternative behind the same LiteLLM proxy.
8. Apache-2.0/MIT models are the default; Llama-licensed judges require legal sign-off.
9. Start with two GPUs: coder 32B AWQ plus fast 7B; add one replica per tier later.

---

## 18. Appendix: alternatives considered

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
