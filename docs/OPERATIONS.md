# AIDLC operations

This runbook describes the planned production topology around the implemented
slices 1–3 and the operations controls delivered by the Kubernetes manifests.
Postgres and Temporal remain external dependencies; the chart in
[`deploy/k8s/aidlc`](../deploy/k8s/aidlc) does not template either system.

## Cluster topology

```text
                          ┌──────────────────────┐
Developer ──TLS/API──────▶│ aidlc-api Service    │
                          │ FastAPI Deployment   │
                          └──────────┬───────────┘
                                     │ Temporal client / Postgres history
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
       aidlc-worker-phases   aidlc-worker-build   litellm-proxy
       aidlc-phases queue    aidlc-build queue    model aliases
                  │                  │                  │
                  └──────────────┬───┘                  ▼
                                 │             vllm-fast/strong/coder/
                                 │             reasoning/embed Services
                                 ▼
                  Temporal frontend + Postgres (external charts)
```

The build worker is a slice-4 target and is isolated from phase workers by task
queue, resources, and sandbox volume. vLLM pods have no egress policy; LiteLLM
is the only model gateway path.

## Components

| Component | Image | Replicas | Queue / port | Resources |
|---|---|---:|---|---|
| `aidlc-api` | AIDLC Docker image | 2 | FastAPI :8000 | 250m/512Mi requests, 1 CPU/1Gi limits |
| `aidlc-worker-phases` | AIDLC Docker image | 2–10 | `aidlc-phases` | 500m/1Gi requests, 2 CPU/2Gi limits |
| `aidlc-worker-build` | AIDLC Docker image | 1+ | `aidlc-build` | 1 CPU/2Gi requests, 4 CPU/8Gi limits |
| `litellm-proxy` | `ghcr.io/berriai/litellm` | 2 | HTTP :4000 | 250m/512Mi requests, 2 CPU/2Gi limits |
| `vllm-fast` | `vllm/vllm-openai` | 1+ | HTTP :8000 | 1 GPU baseline |
| `vllm-coder` | `vllm/vllm-openai` | 1+ | HTTP :8000 | 1 GPU baseline |
| `vllm-strong`, `reasoning` | `vllm/vllm-openai` | 1+ | HTTP :8000 | 2 GPUs each in full profile |
| `vllm-embed` | `vllm/vllm-openai` | 1+ | HTTP :8000 | 1 GPU |

The exact model, GPU count, cache PVC, node selector, tolerations, and
resources are values-driven. See [`values-minimal.yaml`](../deploy/k8s/values-minimal.yaml)
and [`values-full.yaml`](../deploy/k8s/values-full.yaml).

## Install and upgrade

Install in dependency order as described in
[`deploy/k8s/README.md`](../deploy/k8s/README.md):

```bash
helm repo add temporal https://go.temporal.io/helm-charts
helm repo update
# Install Postgres (CloudNativePG or Bitnami), then Temporal.
helm upgrade --install aidlc ./deploy/k8s/aidlc \
  --namespace aidlc --create-namespace \
  -f ./deploy/k8s/values-minimal.yaml
```

Build the application image with the repository [`Dockerfile`](../Dockerfile)
and set `api.image`, `workerPhases.image`, and `workerBuild.image` to its
registry reference. Use an External Secrets Operator or a pre-created Secret
for `AIDLC_DATABASE_URL`, `OPENAI_API_KEY`, and `HF_TOKEN`.

Application upgrades use normal Deployment rolling updates. Pin image tags or
digests and use `helm diff` before applying. Temporal workflow routing changes
must use `workflow.patched` and retain compatibility with in-flight histories.
Postgres schema changes use the existing
`aidlc.storage.migrations.apply` function before application rollout.

## Scaling rules

- Scale `aidlc-worker-phases` for requirements/design/test/deploy activity
  throughput. CPU HPA is the current signal; slice 6 adds Temporal task-queue
  backlog and queue latency as the preferred signal.
- Scale `aidlc-worker-build` independently for work-item fan-out. Give it more
  CPU/memory and ephemeral sandbox capacity than phase workers.
- Scale vLLM replicas per tier when GPU utilization or queue latency requires
  it. Keep coder/reasoning capacity separate from fast-agent capacity.
- Temporal task queues are the isolation boundary: phase workers consume
  `aidlc-phases`, build workers consume `aidlc-build`, and future deployment
  workers consume `aidlc-deploy`.

## Backup and retention

- Use Postgres WAL archiving and PITR; test restoration into an isolated
  namespace at least quarterly.
- Retain run history for 180 days by default, with legal-hold overrides.
- Archive sandbox tarballs, large diffs, and test logs to S3/MinIO in slice 4;
  current artifact bodies remain inline JSONB.
- Retain Temporal history according to the namespace retention policy and
  ensure it covers the 180-day audit window or export the required history.

## Observability

- Temporal UI is the first-line workflow and approval view.
- Scrape vLLM `/metrics` and LiteLLM metrics with Prometheus.
- Slice 6 adds OpenTelemetry spans across workflow, activity, agent, and tool
  boundaries and makes run/queue attributes searchable.
- Alert on activity retry storms, approval age, Temporal task-queue backlog,
  Postgres replication/PITR lag, LiteLLM error rate, and vLLM GPU memory.

## Runbooks

### Worker crash

1. Check Temporal activity retries and the worker pod logs.
2. Confirm the task queue has another healthy worker.
3. Inspect the run's persisted artifacts and events before retrying.
4. If crashes repeat, cordon the image revision and roll back the Deployment;
   do not delete the run history.

### Stuck approval

1. Query the workflow status and identify `phase:attempt`.
2. Confirm the reviewer has the correct project role and that the signal uses
   the matching run ID.
3. Approve or reject through the authenticated API in slice 6; local CLI
   `--by` remains a local-mode identity field.
4. Escalate an expired 14-day wait as `blocked`; never bypass the audit record.

### vLLM out-of-memory

1. Inspect GPU memory and vLLM logs for the tier.
2. Reduce batch/sequence settings or move to the tier's quantized model.
3. Roll back the model alias in LiteLLM to its last healthy target.
4. Increase GPU count/tensor parallelism only after reproducing the sizing
   issue.

### Postgres failover

1. Confirm the Postgres operator has promoted a healthy replica and PITR is
   current.
2. Update the Secret/service endpoint only if the operator does not preserve
   the stable writer address.
3. Restart affected API and workers, then verify repository writes and
   Temporal activity retries.
4. Reconcile any failed migration before resuming new runs.

### Model rollout and rollback

1. Deploy the new vLLM revision alongside the current one.
2. Add it as a non-default LiteLLM model target and exercise health and
   structured-output checks.
3. Swap the LiteLLM alias to promote; monitor errors, latency, and evaluator
   fallback rate.
4. Swap the alias back to the previous target to roll back without changing
   AIDLC workers.

## GPU sizing

| Profile | Tiers | Minimum GPU shape | Use |
|---|---|---|---|
| Minimal | fast 7B + coder 32B AWQ | 2 GPUs, one per tier | Baseline decided in BUILD_GUIDE |
| Full | fast, strong, coder, reasoning, embed | 8+ GPUs depending on tensor parallelism | One replica per tier |
