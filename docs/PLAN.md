# Original plan (historical); see [docs/README.md](README.md) for current status.

# AIDLC Agentic System — Architecture & Build Plan

AI-Driven Development Life Cycle (AIDLC): a multi-agent system that takes a product intent (ticket, PRD, or free text) and drives it through **Requirements → Design → Build → Test & Eval → Deploy**, with human approval gates between phases and full traceability of artifacts.

---

## 1. Design Principles

| Principle | What it means in practice |
|---|---|
| Orchestrator + specialist sub-agents | One master orchestrator owns the SDLC state machine; each phase has its own phase-orchestrator and narrow sub-agents. Agents never talk to each other directly — only via the shared artifact store and their phase-orchestrator. |
| Artifacts, not chat | Every agent consumes and produces typed, versioned artifacts (PRD, ADRs, OpenAPI spec, diffs, test reports, eval scorecards, release notes). Artifacts are the contract between phases. |
| Human-in-the-loop gates | Each phase ends with a gate: `auto-approve` (eval score ≥ threshold and low risk), `review-required`, or `blocked`. Humans approve via UI/Slack/PR comment. |
| Evals everywhere | Every agent output is scored by an evaluator (LLM-as-judge + deterministic checks). Scores drive retries, escalation, and model routing. |
| Observability & replay | All LLM calls, tool calls, and state transitions traced (OpenTelemetry). Any run can be replayed from any checkpoint. |
| Sandboxed execution | Code-touching agents run in isolated containers with scoped repo/CI/cloud credentials. |
| Model-agnostic | A routing layer picks a model per agent/task (cheap for classification, strong for design/code review). |

---

## 2. High-Level Architecture

```
                         ┌──────────────────────────────┐
  Ticket / PRD / Chat ──▶│   Intake API  (REST/Slack/GH) │
                         └──────────────┬───────────────┘
                                        ▼
                    ┌────────────────────────────────────────┐
                    │        MASTER ORCHESTRATOR (SDLC FSM)   │
                    │  INTAKE→REQ→DESIGN→BUILD→TEST/EVAL→     │
                    │  DEPLOY→DONE  (+ backward ChangeRequest)│
                    │  - phase routing, retries, gates        │
                    │  - budget / cost guardrails             │
                    │  - human-approval broker                │
                    └───┬─────────┬─────────┬─────────┬───────┘
                        ▼         ▼         ▼         ▼          ▼
                 ┌──────────┐┌─────────┐┌────────┐┌──────────┐┌────────┐
                 │Req. Orch.││Design O.││Build O.││Test/Eval ││Deploy O│
                 └────┬─────┘└────┬────┘└───┬────┘└────┬─────┘└───┬────┘
                      ▼           ▼         ▼          ▼          ▼
                  sub-agents   sub-agents sub-agents  sub-agents  sub-agents

  ┌───────────────────── Shared Platform Services ───────────────────────┐
  │ Artifact Store (typed, versioned) │ Memory / RAG (repo, docs, runs)  │
  │ Tool Gateway (Git, CI, Cloud, Jira, Slack, browser, sandbox)        │
  │ Model Router │ Eval Service │ Tracing/Observability │ Policy Engine  │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Master Orchestrator

**Role:** owns the end-to-end run as a durable state machine.

- Parse intake → create a `Run` with `RunContext` (repos, env targets, constraints, budget, stakeholders).
- Advance phases; invoke phase orchestrators; enforce entry/exit criteria.
- **Gate broker:** phase eval score + risk class → `auto` / `review` / `block`; posts approval requests (Slack/GitHub/UI), resumes on decision.
- **Retry / escalate:** up to N retries per phase with critique fed back; escalate to human after that.
- **Backward transitions:** e.g. Test finds a design flaw → reopen Design with a `ChangeRequest`.
- Cost/time budgets, kill switch.

Artifacts owned: `Run`, `RunContext`, `PhaseResult`, `GateDecision`, `ChangeRequest`, `Trace`.

---

## 4. Phase Orchestrators & Sub-Agents

### 4.1 Requirements Analysis Orchestrator
Input: raw intent (ticket, PRD, chat, notes). Output: approved `RequirementsSpec`.

| Sub-agent | Responsibility | Output |
|---|---|---|
| **Intake & Context Agent** | Normalizes input, pulls linked tickets/docs, identifies affected repos/services via RAG. | `IntakeSummary` |
| **Stakeholder Clarifier Agent** | Detects ambiguity/gaps; generates targeted questions; async Q&A loop with humans. | `ClarificationLog` |
| **Requirements Author Agent** | Functional + non-functional requirements, user stories, acceptance criteria (Gherkin). | `RequirementsSpec` |
| **Domain/Compliance Agent** | Checks domain rules, security/privacy/regulatory constraints, org policies. | `ComplianceNotes` |
| **Feasibility & Scope Agent** | Sizes work, flags tech risks, proposes MVP vs. later slices. | `ScopeAssessment` |
| **Requirements Evaluator** | Scores completeness, testability, consistency, traceability. | `EvalScorecard` |

Gate: product-owner approval (or auto if score ≥ threshold and low risk).

### 4.2 Design Orchestrator
Input: `RequirementsSpec`. Output: `DesignPackage`.

| Sub-agent | Responsibility | Output |
|---|---|---|
| **Codebase Analyst Agent** | Maps existing architecture, modules, dependencies, conventions (AST + RAG). | `CodebaseMap` |
| **Solution Architect Agent** | Proposes 1–3 options with trade-offs; records decisions. | `ADRs`, `ArchitectureDiagram` (Mermaid/C4) |
| **API & Data Modeler Agent** | Interfaces (OpenAPI/GraphQL/proto), schemas, migrations, events. | `APISpec`, `DataModel` |
| **Security / Threat Model Agent** | STRIDE threat model, authn/authz, secrets handling. | `ThreatModel` |
| **Task Decomposer Agent** | Ordered, independently-mergeable work items with file-level hints and dependency DAG. | `WorkPlan` |
| **Design Evaluator** | Requirement coverage (traceability matrix), consistency with `CodebaseMap`, NFR alignment. | `EvalScorecard`, `TraceabilityMatrix` |

Gate: tech-lead approval.

### 4.3 Build Orchestrator
Input: `WorkPlan`. Output: mergeable PR(s). Work items run in parallel where the DAG allows, each in its own sandbox/branch.

| Sub-agent | Responsibility | Output |
|---|---|---|
| **Scaffold / Env Agent** | Prepares sandbox, installs deps, verifies build/test baseline, creates branch. | `EnvReport` |
| **Coder Agent** (per WorkItem) | Implements change following conventions; small focused commits. | `CodeDiff` |
| **Unit-Test Writer Agent** | Writes/updates unit tests alongside code (TDD option). | `TestDiff` |
| **Static Analysis Agent** | Lint, type-check, format, SAST, dependency audit; auto-fixes mechanical issues. | `StaticReport` |
| **Code Reviewer Agent** | Independent review (different model/prompt): correctness, design conformance, security. Loops with Coder. | `ReviewReport` |
| **Integrator Agent** | Rebases, resolves clerical conflicts, assembles PR linking spec/ADRs, opens PR. | `PullRequest` |
| **Build Evaluator** | Diff vs. acceptance criteria, review-loop convergence, CI status. | `EvalScorecard` |

Gate: CI green + human PR review (auto-merge allowed for low-risk, high-score).

### 4.4 Testing & Evals Orchestrator
Input: PR(s) + `RequirementsSpec`. Output: `QualityReport`.

| Sub-agent | Responsibility | Output |
|---|---|---|
| **Test Planner Agent** | Test matrix from acceptance criteria and risk areas. | `TestPlan` |
| **Integration / API Test Agent** | Generates & runs API/contract tests against ephemeral env. | `IntegrationResults` |
| **E2E / UI Test Agent** | Drives app via browser (Playwright/computer-use), records video, asserts acceptance criteria. | `E2EResults` |
| **Performance & Load Agent** | Load/latency tests vs. NFR targets. | `PerfResults` |
| **Security Test Agent** | DAST, CVEs, secrets scan, authz probes. | `SecurityResults` |
| **Regression Triage Agent** | Classifies failures (product bug / test bug / flake / env); files `ChangeRequest`s back to Build or Design. | `TriageReport` |
| **Eval Harness Agent** (AI features) | Golden datasets, LLM-judge rubrics, regression thresholds for LLM-powered product features. | `ModelEvalReport` |
| **Quality Evaluator** | Aggregates into go/no-go with requirement-level traceability. | `QualityReport` |

Gate: QA-lead approval / auto if all thresholds met.

### 4.5 Deployment Orchestrator
Input: approved artifact + `QualityReport`. Output: release in target env.

| Sub-agent | Responsibility | Output |
|---|---|---|
| **Release Manager Agent** | Versioning, changelog, release notes, tags. | `ReleaseNotes` |
| **IaC / Config Agent** | Terraform/Helm/K8s manifests, feature flags, env config; plan diff. | `InfraPlan` |
| **Deployment Executor Agent** | Runs pipeline via existing CI/CD (canary/blue-green); waits for health checks. | `DeployLog` |
| **Observability Verifier Agent** | Watches SLOs, error rates, logs for a soak window vs. baseline. | `SoakReport` |
| **Rollback Agent** | Auto-rollback on SLO breach; files incident `ChangeRequest`. | `RollbackReport` |
| **Deploy Evaluator** | Release hygiene, soak health, runbook/docs completeness. | `EvalScorecard` |

Gate: change-approval / on-call approval for prod.

---

## 5. Cross-Cutting Services

- **Eval Service:** rubric library, LLM-judge (rubric/pairwise), deterministic validators (schema, coverage, lint), per-agent score history → model routing + prompt regression tests.
- **Memory / RAG:** repo index (code + docs), past runs, ADR history, org conventions.
- **Tool Gateway:** MCP tool servers — Git/GitHub, CI, Jira/Linear, Slack, cloud CLIs, browser, sandbox exec; policy engine enforces least privilege per agent.
- **Human Approval Broker:** unified gate UI (web + Slack + PR comments), audit log.
- **Observability:** OTel traces per run/agent/tool call; cost dashboard; replay.

---

## 6. Proposed Tech Stack (adjustable)

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.12 (agents), TypeScript (UI) | LLM/agent ecosystem |
| Agent framework | LangGraph (durable graph FSM) — alt: Temporal + custom | Checkpointing, human-in-loop interrupts, replay |
| LLM access | LiteLLM router (OpenAI / Anthropic / Bedrock / Azure) | Model-agnostic |
| Tools | MCP servers | Standard protocol |
| Artifact store | Postgres (JSONB, versioned) + S3 blobs | Typed, auditable |
| Vector / RAG | pgvector | Simple infra |
| Sandbox | Docker per run | Isolation |
| Evals | Custom harness + promptfoo / DeepEval | Rubrics + regression |
| Tracing | OpenTelemetry → Langfuse | Observability |
| UI | Next.js dashboard | Runs, gates, artifacts |
| CI/CD | GitHub Actions | Existing infra |

---

## 7. Target Repository Layout

```
aidlc/
  core/            # Run, state machine, artifact models (pydantic), gate broker
  orchestrators/   # master, requirements, design, build, test_eval, deploy
  agents/          # one module per sub-agent (prompt, tools, output schema)
  evals/           # rubrics, judges, golden sets, agent regression tests
  tools/           # MCP servers: git, ci, jira, slack, sandbox, browser, cloud
  memory/          # indexing + retrieval
  services/        # FastAPI api, workers, approval broker
  ui/              # Next.js dashboard
  infra/           # docker-compose, Helm for the platform itself
  tests/
```

---

## 8. Build Roadmap (incremental, each step demoable)

| Step | Deliverable |
|---|---|
| 0 | Skeleton: repo, artifact schemas, master FSM with stub phases, tracing, docker-compose (Postgres, Langfuse). |
| 1 | Requirements phase: Intake → Clarifier → Author → Evaluator; Slack/UI gate. |
| 2 | Design phase: Codebase Analyst, Architect (ADRs), Task Decomposer, traceability matrix. |
| 3 | Build phase: sandbox, Coder + Test Writer + Static Analysis + Reviewer loop, PR creation. |
| 4 | Test & Eval phase: Test Planner, API + E2E agents, triage & backward ChangeRequests, QualityReport. |
| 5 | Deploy phase: release notes, IaC plan, CI/CD trigger, soak + rollback. |
| 6 | Eval service & hardening: agent rubrics/golden sets, score-based model routing, cost guardrails, replay UI. |
| 7 | Dogfood: run AIDLC on its own repo for a real feature end-to-end. |

Estimate: steps 0–2 in one session, 3–4 in a second, 5–7 in a third; external waits are LLM/cloud/CI credentials and Slack app setup.

---

## 9. Open Decisions (needed before building)

1. Framework: LangGraph (recommended) vs. Temporal-based custom orchestration.
2. LLM providers available (OpenAI / Anthropic / Bedrock / Azure)?
3. Target repos & CI/CD the system operates on (GitHub Actions? Jenkins? K8s?).
4. First approval channel: Slack, GitHub PR comments, or web UI?
5. First vertical slice: all 5 phases shallow, or Requirements→Build deep first?
