# AIDLC documentation

This directory is the documentation entry point for the AIDLC repository. The
implementation currently combines LangGraph phase subgraphs with an optional
Temporal workflow and Postgres shared history. The default remains the local
mock/file/in-process path.

## Reading order

1. [`../README.md`](../README.md) — quickstart, architecture, configuration, and
   the local versus distributed run commands.
2. [`DESIGN.md`](DESIGN.md) — the implemented single-machine lifecycle, agents,
   artifacts, evaluators, gates, storage, and interfaces.
3. [`DISTRIBUTED_DESIGN.md`](DISTRIBUTED_DESIGN.md) — Temporal/Postgres
   architecture, schema, workflow behavior, migration slices, and resolved
   decisions.
4. [`BUILD_GUIDE.md`](BUILD_GUIDE.md) — development-team operating guide,
   exact interfaces, verified local stack recipe, and acceptance criteria.
5. [`OPERATIONS.md`](OPERATIONS.md) — cluster topology, install/upgrade,
   scaling, backup, observability, and incident runbooks.
6. [`SECURITY.md`](SECURITY.md) — identity, authorization, secrets, tenancy,
   sandbox, supply-chain, and audit decisions.
7. [`DEPLOY_DESIGN.md`](DEPLOY_DESIGN.md) — real Deploy target abstraction,
   promotion workflow, rollback, and kind-based acceptance plan.
8. [`PLAN.md`](PLAN.md) — the original historical architecture/build plan.

## Status

| Slice | Status | Code paths | Acceptance focus |
|---|---|---|---|
| 1. Storage protocols and Postgres backends | **Implemented** | [`aidlc/storage`](../aidlc/storage), [`aidlc/core/agent.py`](../aidlc/core/agent.py), [`aidlc/core/evals.py`](../aidlc/core/evals.py), [`aidlc/core/gate.py`](../aidlc/core/gate.py) | File defaults remain intact; Postgres artifacts, traces, scorecards, gates, events, and migrations work. |
| 2. Postgres LangGraph checkpoints | **Implemented** | [`aidlc/orchestrators/master.py`](../aidlc/orchestrators/master.py), [`tests/test_storage_postgres.py`](../tests/test_storage_postgres.py) | `AIDLC_DATABASE_URL` selects `PostgresSaver`; local mode uses SQLite. |
| 3. Temporal phase execution | **Implemented** | [`aidlc/distributed`](../aidlc/distributed), [`tests/test_temporal.py`](../tests/test_temporal.py), [`deploy/docker-compose.yml`](../deploy/docker-compose.yml) | Phase activities, Signals, approval waits, retries, triage routing, and status queries work. |
| 4. Distributed build swarm | Planned | [`aidlc/orchestrators/build.py`](../aidlc/orchestrators/build.py), future `aidlc-build` activities | Parallel per-work-item activities, portable sandboxes, and budget guards. |
| 5. Project memory | Planned | Future project-memory storage and agent inputs | Relational project memory first; pgvector remains deferred. |
| 6. Team operations and observability | Planned | [`aidlc/services/api.py`](../aidlc/services/api.py), [`OPERATIONS.md`](OPERATIONS.md), [`SECURITY.md`](SECURITY.md) | OTel, run listing, API keys, and two-machine operation. |
| 7. Model routing and serving | Planned | [`aidlc/core/llm.py`](../aidlc/core/llm.py), [`deploy/k8s`](../deploy/k8s), future proxy/infra examples | Coder/reasoning tiers, per-agent overrides, aliases/fallbacks, and serving deployment. |

The status table is deliberately separate from the historical plan: slices 1–3
are present in this checkout, while slices 4–7 are design targets.
