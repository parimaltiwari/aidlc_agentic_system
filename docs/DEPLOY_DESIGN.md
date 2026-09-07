# Real Deploy phase design

The current Deploy phase is simulation-only. This addendum defines the target
that replaces simulation for real environments while preserving deterministic
tests and the existing artifact contracts.

## Target abstraction

```python
class DeployTarget(Protocol):
    def plan(self, release: ReleaseNotes, infra_plan: InfraPlan) -> InfraPlan: ...
    def apply(self, plan: InfraPlan) -> DeployLog: ...
    def verify(self, env: str, duration: int) -> SoakReport: ...
    def rollback(self, reason: str) -> RollbackReport: ...
```

Implementations arrive in this order:

1. `KubernetesHelmTarget` is the default real target. It runs `helm upgrade
   --install --atomic`; rolling is the default strategy, canary uses Argo
   Rollouts when configured, and blue-green swaps a Service selector.
2. `GitOpsTarget` opens a PR to an environment repository for ArgoCD or Flux
   reconciliation. This is preferred for production because cluster mutation
   stays in the GitOps control plane.
3. `SimulationTarget` is the current behavior and remains the default for unit
   and mock tests.

## Artifacts and extensions

Current exact fields in `aidlc/core/artifacts.py` are:

```text
ReleaseNotes(version, highlights, breaking_changes, body)
InfraPlan(changes, strategy)
DeployLog(environment, steps, healthy)
SoakReport(duration_minutes, slo_breaches, healthy)
RollbackReport(triggered, reason)
```

The small target-specific extensions are:

- `InfraPlan`: `target`, `environment`, and `manifests: list[str]`.
- `DeployLog`: `revision`.
- `SoakReport`: `metrics: dict`.

These additions preserve the existing fields and make the release target,
environment, applied revision, and measured SLO data queryable.

## Agent and activity responsibilities

- `ReleaseManagerAgent` is unchanged and produces `ReleaseNotes`.
- `IaCConfigAgent` produces Helm values or Kustomize patches for the selected
  target instead of a provider-neutral description.
- `DeploymentExecutorAgent` becomes a deterministic tool node that calls
  `DeployTarget.apply`; it is not an LLM decision.
- `ObservabilityVerifierAgent` evaluates Prometheus/SLO queries from
  `AIDLC_PROM_URL` over the soak window, then an LLM summarizes the evidence.
- `RollbackAgent` calls `DeployTarget.rollback` when the soak is unhealthy.

## Promotion and credentials

Promotion is a Temporal child workflow per environment:

```text
dev (auto) ──► staging (auto when low risk) ──► prod (always reviewer gate)
       │                 │                              │
       └── deploy activity on aidlc-deploy queue ───────┘
```

Each environment has its own gate Signal. Deployment activities run only on
`aidlc-deploy` workers holding cluster credentials; phase, build, and API
workers never receive those credentials.

Deploy activity idempotency is keyed by
`run_id:environment:revision`. Helm release names derive from the project
identifier and are stable across retries.

## Sequence

```text
AidlcRunWorkflow
      │ child workflow(environment)
      ▼
ReleaseManager ──► IaCConfig ──► DeployTarget.plan
                                      │
                                      ▼
                         deploy activity on aidlc-deploy
                                      │
                                      ▼
                         Helm/GitOps target.apply
                                      │
                                      ▼
                  Prometheus verify(env, soak_window)
                         │ healthy?     │ unhealthy?
                         ▼              ▼
                   human/auto gate   target.rollback
                         │              │
                         └──────► next environment / blocked
```

## Failure handling

- `--atomic` Helm upgrades roll back failed Kubernetes releases.
- Temporal retries are safe because the idempotency key and stable Helm
  release name make apply repeatable.
- A failed health check records `SoakReport`, calls rollback, and blocks
  promotion until a reviewer resolves the event.
- GitOps failures remain visible as an environment-repository PR/check failure;
  the workflow does not claim deployment until reconciliation and verification
  succeed.
- Missing Prometheus data is unhealthy, not an implicit pass.

## Acceptance and test plan

1. `SimulationTarget` keeps all existing mock phase tests green.
2. A kind-based e2e creates a namespace, installs a sample chart with
   `KubernetesHelmTarget`, verifies the revision, injects an unhealthy metric,
   exercises rollback, and confirms idempotent retry.
3. A GitOps test uses a fake environment repository and verifies that only a PR
   is opened, never a protected-branch push.
4. Target unit tests cover rolling, canary, blue-green, `--atomic`, failed
   verification, rollback, and malformed manifests.
5. A Temporal test runs dev→staging→prod and proves prod requires a reviewer
   Signal while low-risk staging proceeds automatically.
