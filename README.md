# AIDLC

AIDLC is a typed, multi-agent development lifecycle that moves an intent through
Requirements → Design → Build → Test/Eval → Deploy. LangGraph owns the phase
subgraphs and agent contracts; optional Temporal owns durable cross-phase
execution and approval waits; Postgres provides shared history when enabled.
Mock/file/in-process execution remains the default and needs no API keys.

```text
CLI / FastAPI
     │
     ▼
Temporal workflow (optional) ── approval Signals ──► durable status
     │ phase activities
     ▼
LangGraph phase graphs → specialist agents → MockLLM / LiteLLM gateway
     │
     └──────────────► Postgres history: runs, artifacts, traces,
                      scorecards, gates, CRs, checkpoints
```

## Quickstart: local mock mode

```bash
uv sync
uv run aidlc run "Add password reset via email to the user service" --auto-approve
```

This uses the mock provider, file artifacts/traces under `./runs`, and a SQLite
LangGraph checkpoint. A high-risk local run pauses at a LangGraph gate:

```bash
uv run aidlc run "Add password reset" --risk high
uv run aidlc status RUN_ID
uv run aidlc approve RUN_ID --by dev
```

## Quickstart: distributed Temporal mode

Start the self-hosted local stack (Postgres creates both `aidlc` and `temporal`
databases):

```bash
docker compose -f deploy/docker-compose.yml up -d
```

In another terminal, run the phase worker:

```bash
AIDLC_DATABASE_URL=postgresql://aidlc:aidlc@127.0.0.1:5432/aidlc \
  uv run aidlc worker --address 127.0.0.1:7233 --namespace default
```

Start a mock Temporal run:

```bash
AIDLC_DATABASE_URL=postgresql://aidlc:aidlc@127.0.0.1:5432/aidlc \
AIDLC_EXECUTION=temporal \
AIDLC_TEMPORAL_ADDRESS=127.0.0.1:7233 \
AIDLC_TEMPORAL_NAMESPACE=default \
AIDLC_LLM_PROVIDER=mock \
  uv run aidlc run "add health endpoint" --risk high --execution temporal
```

Query and approve each gate until the status is `completed`:

```bash
AIDLC_EXECUTION=temporal \
AIDLC_TEMPORAL_ADDRESS=127.0.0.1:7233 \
AIDLC_TEMPORAL_NAMESPACE=default \
  uv run aidlc status RUN_ID --execution temporal

AIDLC_EXECUTION=temporal \
AIDLC_TEMPORAL_ADDRESS=127.0.0.1:7233 \
AIDLC_TEMPORAL_NAMESPACE=default \
  uv run aidlc approve RUN_ID --by dev --execution temporal
```

The Temporal UI is available at <http://127.0.0.1:8080>. Tear down the stack
when finished:

```bash
docker compose -f deploy/docker-compose.yml down -v
```

## Configuration

| Variable | Default / meaning |
|---|---|
| `AIDLC_DATABASE_URL` | Unset: file storage and SQLite checkpoints; set: Postgres shared history and checkpoints. |
| `AIDLC_EXECUTION` | Unset: in-process; `temporal`: Temporal client path. |
| `AIDLC_TEMPORAL_ADDRESS` | `localhost:7233`. |
| `AIDLC_TEMPORAL_NAMESPACE` | `default`. |
| `AIDLC_LLM_PROVIDER` | `mock` (offline default), `litellm`, or `ollama`. |
| `AIDLC_MODEL` | Fast-agent model setting. |
| `AIDLC_MODEL_STRONG` | Strong/evaluator model setting. |
| `AIDLC_AUTO_APPROVE` | `1` bypasses review gates. |
| `AIDLC_RUNS_DIR` | `./runs`; file artifacts, traces, sandboxes, and SQLite checkpoints. |

## Model serving

Agents call models through `aidlc/core/llm.py` (`mock`, `litellm`, or `ollama`).
For a laptop, see the Ollama section of [`docs/DESIGN.md`](docs/DESIGN.md)
(CPU-only inference is slow — tens of seconds per call). For an enterprise,
point `AIDLC_LLM_PROVIDER=litellm` at a LiteLLM proxy fronting vLLM/TGI-hosted
open-source models; the serving fleet, model catalogue, and per-agent model
assignment matrix are in
[`docs/DISTRIBUTED_DESIGN.md`](docs/DISTRIBUTED_DESIGN.md) §14–§15 (slice 7).

## Documentation

Start with [`docs/README.md`](docs/README.md), then read:

1. [`docs/DESIGN.md`](docs/DESIGN.md) — implemented local architecture.
2. [`docs/DISTRIBUTED_DESIGN.md`](docs/DISTRIBUTED_DESIGN.md) — Temporal/Postgres
   design and migration status.
3. [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md) — interfaces, verified stack
   recipe, and future-slice acceptance criteria.
4. [`docs/PLAN.md`](docs/PLAN.md) — original historical plan.

## Verification

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Postgres integration tests are enabled with:

```bash
AIDLC_TEST_DATABASE_URL=postgresql://aidlc:aidlc@127.0.0.1:55432/aidlc \
  uv run pytest -q
```

## Layout

```text
aidlc/
├── aidlc/agents/          # phase-specialist agents and mock handlers
├── aidlc/core/            # artifacts, state, LLMs, evaluators, gates
├── aidlc/orchestrators/   # master and five LangGraph phase graphs
├── aidlc/storage/         # file/Postgres protocols, backends, migrations
├── aidlc/distributed/     # Temporal models, workflow, activities, client
├── aidlc/tools/           # sandbox, static analysis, tests, git helpers
├── aidlc/services/        # FastAPI service
├── deploy/                # Compose stack, Postgres init SQL, env example
├── docs/                  # architecture, design, build guide, plan
└── tests/                 # mock, Postgres, and Temporal tests
```
