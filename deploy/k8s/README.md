# AIDLC Kubernetes deployment

This chart deploys the AIDLC API, Temporal phase workers, the slice-4-target
build worker, LiteLLM, and optional vLLM model tiers. It deliberately does not
install Postgres or Temporal. Install the
[official Temporal Helm chart](https://github.com/temporalio/helm-charts) and a
Postgres operator/chart (CloudNativePG or Bitnami PostgreSQL) first, then set
their service DNS names in `external.postgres` and `external.temporal`.

## Install order

1. Create namespaces and install Postgres. Create the `aidlc` database and a
   secret containing `AIDLC_DATABASE_URL`.
2. Install Temporal in its own namespace, backed by its own database, and note
   the frontend service address.
3. Install this chart in the AIDLC namespace. Use `values-minimal.yaml` for the
   two-GPU baseline or `values-full.yaml` for one replica per model tier.

Example:

```bash
kubectl create namespace database
kubectl create namespace temporal
kubectl create namespace aidlc

# Install Postgres using CloudNativePG or Bitnami, then install Temporal.
helm repo add temporal https://go.temporal.io/helm-charts
helm repo update
helm upgrade --install temporal temporal/temporal \
  --namespace temporal --create-namespace \
  --set server.config.persistence.default.store=postgres12

# The exact Postgres/Temporal chart values are platform-specific. Configure
# the AIDLC chart with their in-cluster service names:
helm upgrade --install aidlc ./deploy/k8s/aidlc \
  --namespace aidlc --create-namespace \
  -f ./deploy/k8s/values-minimal.yaml \
  --set external.postgres.namespace=database \
  --set external.temporal.namespace=temporal \
  --set secrets.existingSecret=aidlc-runtime
```

The external secret must contain `AIDLC_DATABASE_URL`, `OPENAI_API_KEY`, and
`HF_TOKEN` keys as applicable. Do not put production credentials in a values
file. The chart's default generated Secret is convenient for development only.

## Validation and local placeholder install

The repository's validation uses the static `helm`, `kubectl`, and `kind`
binaries, then runs:

```bash
helm lint ./deploy/k8s/aidlc
helm template aidlc ./deploy/k8s/aidlc -f ./deploy/k8s/values-minimal.yaml
helm template aidlc ./deploy/k8s/aidlc -f ./deploy/k8s/values-full.yaml
kind create cluster --name aidlc
kubectl apply --dry-run=server -f <(
  helm template aidlc ./deploy/k8s/aidlc \
    -f ./deploy/k8s/values-minimal.yaml
)
```

For a live kind install without downloading model or application images, use
the checked-in placeholder overrides:

```bash
helm upgrade --install aidlc ./deploy/k8s/aidlc \
  --namespace aidlc --create-namespace \
  -f ./deploy/k8s/values-kind.yaml
kubectl get deployments,services,pods -n aidlc
helm uninstall aidlc --namespace aidlc
kind delete cluster --name aidlc
```

`values-kind.yaml` uses the existing `busybox:1.36` image with
`sleep infinity`, disables vLLM tiers, and is only a rendering/install smoke
test. It is not a production configuration.
