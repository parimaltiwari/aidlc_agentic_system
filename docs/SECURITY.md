# AIDLC security design

These are the security decisions for the distributed deployment. Controls that
are not implemented in slices 1–3 are explicitly assigned to a later slice or
post-MVP work rather than implied to exist today.

## Identity and authorization

- FastAPI accepts `Authorization: Bearer <api-key>` per developer in slice 6.
- Keys are hashed in a Postgres `api_keys` table; plaintext keys are never
  persisted:

  ```sql
  CREATE TABLE api_keys (
    id bigserial PRIMARY KEY,
    project_id text NOT NULL REFERENCES projects(id),
    subject text NOT NULL,
    key_hash text NOT NULL UNIQUE,
    role text NOT NULL CHECK (role IN ('developer', 'reviewer', 'admin')),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    revoked_at timestamptz
  );
  CREATE INDEX api_keys_project_subject_idx ON api_keys(project_id, subject);
  ```

- OIDC/JWT is a later replacement behind the same FastAPI authentication
  dependency.
- Roles are `developer`, `reviewer`, and `admin`. Developers start and approve
  runs for their own project; reviewers approve any gate in the project; admins
  manage projects, keys, and policy.
- High- and medium-risk gates require a reviewer. The authenticated identity is
  recorded as `approved_by`; CLI `--by` is honored only in local mode and is
  not an identity assertion for the API.

## Secrets and model gateway

- Kubernetes Secrets or External Secrets Operator hold database URLs, API
  keys, HF tokens, and gateway credentials.
- Secrets never enter artifacts. Tracing redacts case-insensitive
  `api_key`, `token`, and `password` patterns.
- LiteLLM uses virtual keys per team with budgets and rate limits. Prompt and
  response logging is off by default.
- vLLM has no egress. Workers call only Postgres, Temporal, and LiteLLM;
  LiteLLM calls only vLLM and required cluster DNS.

## Sandbox and repository access

- Slice 4 runs each build work item in an ephemeral container, preferably
  gVisor or Kata, with no network, a read-only source mount, and CPU, memory,
  and wall-time limits. Only the diff artifact leaves the sandbox.
- Repository access uses a GitHub App or deploy key per project and PR-only
  writes. Protected branches are never pushed by AIDLC, matching the existing
  `PullRequestArtifact`.
- The `projects` table is the tenancy boundary. Every query is scoped by
  `project_id`; a per-project Temporal namespace is optional for stronger
  isolation.

## Supply chain and audit

- Dependencies are pinned in `uv.lock`.
- Release images are signed with cosign and accompanied by an SBOM.
- `run_events`, `gate_decisions`, and Temporal history are the audit trail.
- Audit records are retained for the 180-day default history window in
  [`OPERATIONS.md`](OPERATIONS.md).

## STRIDE-lite threat model

| Threat | Example | Mitigations |
|---|---|---|
| Spoofing | Stolen developer API key | Bearer key rotation/revocation, hashed `api_keys`, TLS, short expiry |
| Tampering | Repo prompt changes generated plan | Read-only source mount, artifact hashes, PR-only writes, reviewer gates |
| Repudiation | Developer denies an approval | Authenticated `approved_by`, `gate_decisions`, `run_events`, Temporal history |
| Information disclosure | Secret appears in an artifact or trace | Secret injection, schema boundaries, tracer redaction, logging off by default |
| Denial of service | Unbounded work item or model requests | Risk gates, per-team LiteLLM budgets, sandbox limits, queue quotas |
| Elevation of privilege | Developer approves another project | Project-scoped authorization and reviewer/admin role checks |
| Prompt injection | Malicious instructions in repository contents | Treat repo text as untrusted data, constrained agent prompts, review gates, no network |
| Supply-chain compromise | Poisoned dependency or model image | `uv.lock`, image digests/signatures, SBOM, approved model/license catalogue |
| Cluster escape | Generated test exploits the host | Ephemeral sandbox, gVisor/Kata, read-only mounts, dropped capabilities |
| Model exfiltration | vLLM reaches an external endpoint | vLLM egress deny policy and LiteLLM-only gateway path |

## Implementation checklist

| Control | Delivery |
|---|---|
| API-key authentication and `api_keys` table | Slice 6 |
| Project-scoped roles and reviewer gates | Slice 6 |
| OIDC/JWT | Post-MVP |
| Secret manager / External Secrets Operator | Slice 6 |
| Tracer redaction and gateway logging policy | Slice 6 |
| Ephemeral no-network sandbox | Slice 4 |
| GitHub App and PR-only repository access | Slice 4 |
| Per-project tenancy enforcement | Slice 6 |
| Signed images and SBOM verification | Slice 6 |
| Model aliases, budgets, and fallback policy | Slice 7 |
| gVisor/Kata hardening review | Post-MVP if the platform cannot provide it in slice 4 |
