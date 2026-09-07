# AIDLC Agentic System — Design Document

This document describes the architecture of the AIDLC (AI Development Life Cycle)
agentic system as implemented in this repository. Everything below is grounded in
the current code; file paths are given so each claim can be checked.

Contents

1. Purpose and principles
2. Why this is a multi-agent framework
3. Overall flow (master state machine)
4. Shared contracts: state, artifacts, agents, LLM, evaluators, gates
5. Phase 1 — Requirements Analysis
6. Phase 2 — Design
7. Phase 3 — Build
8. Phase 4 — Test & Eval
9. Phase 5 — Deploy
10. Cross-cutting services (storage, tracing, tools, checkpoints)
11. Interfaces: CLI and HTTP API
12. Running with a real open-source LLM
13. Known limitations and next steps

---

## 1. Purpose and principles

The system turns a one-line product intent (e.g. *"Add rate limiting to the
login endpoint"*) into requirements, a design, sandboxed code with tests, a test
& quality verdict, and a (simulated) deployment — with human approval gates and
automatic quality evaluation between every phase.

Design principles:

| Principle | How it shows up in the code |
|---|---|
| **Typed artifacts, not chat history** | Every agent emits a Pydantic model (`aidlc/core/artifacts.py`); phases communicate only through these artifacts stored in state. `extra="forbid"` rejects hallucinated fields. |
| **Small, single-purpose agents** | ~30 agent classes, each with one system prompt, one output schema, and an explicit list of input artifacts (`relevant_artifacts`). |
| **Deterministic where possible, LLM where necessary** | Coverage, pass/fail, traceability, DAG validity, static analysis and test execution are computed in code, never asked of the model. LLMs author content; code decides. |
| **Evaluate then gate, every phase** | Each phase ends with an `Evaluator` (deterministic checks + LLM judge) followed by a `GatePolicy` decision (`auto` / `review` / `block`). |
| **Human-in-the-loop, durable** | Gates use LangGraph `interrupt()`; runs checkpoint to SQLite and resume with `Command(resume=...)` — hours or days later, from another process. |
| **Never touch the user's repo** | Build works in `runs/<run_id>/sandbox`; an input repo is *copied* there before modification. |
| **Provider-agnostic LLM** | A 1-method `LLMClient` protocol with `mock`, `litellm` (hosted) and `ollama` (local open-source) implementations. |

---

## 2. Why this is a multi-agent framework

"Multi-agent" here means more than several prompts in a loop. The framework has
the properties that distinguish a multi-agent system from a single agent:

1. **Role specialisation.** Each agent is a class with a distinct role, system
   prompt, model tier (`fast` / `strong`), input filter and output schema
   (`BaseAgent`, `aidlc/core/agent.py`). A `ThreatModelAgent` cannot emit code;
   a `CoderAgent` cannot change requirements.

2. **Hierarchical orchestration.** A master LangGraph state machine
   (`aidlc/orchestrators/master.py`) delegates to five phase orchestrators,
   each itself a compiled LangGraph subgraph (`aidlc/orchestrators/*.py`). The
   master reasons about *phases* (route, retry, block, back-hop); phase graphs
   reason about *agents* (sequence, fan-out/fan-in, per-work-item loops).

3. **Explicit communication protocol.** Agents never see each other's chat.
   They read named artifacts from shared state and write new named artifacts.
   Each agent declares `relevant_artifacts` so it receives only what it needs
   — this is both a context-window optimisation and an information boundary.

4. **Parallelism.** Independent agents fan out: Requirements runs
   `compliance ∥ scope`; Design runs `api ∥ data ∥ threat`. Build fans out
   dynamically over the work plan's items (topologically sorted by
   `depends_on`).

5. **Critic / judge agents.** Evaluators (`aidlc/core/evals.py`) are agents
   whose job is to score other agents' output against a rubric, combining
   deterministic checks with an LLM judge on the `strong` tier. Reviewers
   (`CodeReviewerAgent`) critique coder output per work item.

6. **Feedback and re-planning.** A failing evaluator re-runs the phase (≤ 2
   retries). Test triage can emit a `ChangeRequest` that routes the run
   backwards to Design or Build (≤ 2 hops). This is closed-loop control, not a
   linear pipeline.

7. **Humans as first-class participants.** Gates can pause the whole system and
   wait for an approval that arrives via CLI or HTTP, then resume exactly where
   it stopped.

8. **Observability per agent.** Every agent call is traced (`trace.jsonl`) with
   duration and success, and every artifact is versioned on disk, so the
   contribution of each agent to the final result is auditable.

---

## 3. Overall flow (master state machine)

```
                ┌──────────────┐
  intent ──────▶│ requirements │──gate──▶ route
                └──────────────┘            │
                                            ▼
                ┌──────────────┐
                │    design    │◀──────────────────┐  (ChangeRequest → design)
                └──────────────┘                   │
                       │ gate → route              │
                       ▼                           │
                ┌──────────────┐                   │
                │    build     │◀──────────────┐   │  (ChangeRequest → build)
                └──────────────┘               │   │
                       │ gate → route          │   │
                       ▼                       │   │
                ┌──────────────┐   triage      │   │
                │  test_eval   │───────────────┴───┘
                └──────────────┘
                       │ gate → route
                       ▼
                ┌──────────────┐
                │    deploy    │──gate──▶ completed
                └──────────────┘

  At every route:   evaluator failed & retries<2  → rerun same phase
                    evaluator failed & retries==2 → blocked
                    gate = block / rejected       → blocked
                    gate = review (no auto-approve) → interrupt → awaiting_approval
```

Implementation (`aidlc/orchestrators/master.py`):

- `build_master_graph()` adds one node per phase (`_phase_node` wraps the
  compiled subgraph, invokes it with the full state, and returns only the
  *new* artifacts / scorecards / gate decisions / log lines so LangGraph
  reducers merge correctly).
- `_route_update()` runs after each phase:
  1. gate `block` or status `blocked` → `status="blocked"`, END.
  2. latest scorecard `passed=False` → `retries[phase] += 1`; rerun if `< 2`,
     else block.
  3. after `test_eval`, first `TriageItem` with a `target_phase` →
     `retries["backward"] += 1`, append `ChangeRequest CR-n`, route to
     `design` or `build`; block on the third hop.
  4. otherwise advance: requirements → design → build → test_eval → deploy → END.
- `run_pipeline(intent, context, run_id)` builds the initial `AidlcState`,
  invokes the graph with `thread_id=run_id`; if the checkpoint has pending
  interrupts, status becomes `awaiting_approval`.
- `resume_run(run_id, approved, by)` invokes the same graph with
  `Command(resume={"approved", "by"})`.
- Checkpointer: `SqliteSaver` on `$AIDLC_RUNS_DIR/checkpoints.sqlite`.

Run status values: `running | awaiting_approval | completed | blocked | failed`.

---

## 4. Shared contracts

### 4.1 State (`aidlc/core/state.py`)

`AidlcState` (TypedDict) is the single shared blackboard:

| Key | Type / reducer | Meaning |
|---|---|---|
| `run_id` | str | Thread id for checkpoints, artifact dir name |
| `intent` | str | User's request |
| `context` | dict (`RunContext`) | `repo_path`, `target_env`, `risk`, `budget_usd`, `stakeholders` |
| `phase` | str | Current phase |
| `artifacts` | dict, **merge** reducer | `artifact_key → serialized Pydantic model` |
| `scorecards` | list, **append** | `EvalScorecard`s in order |
| `gate_decisions` | list, **append** | `GateDecision`s in order |
| `change_requests` | list | `ChangeRequest`s from backward routing |
| `retries` | dict[str,int] | per-phase and `"backward"` counters |
| `log` | list, **append** | human-readable progress lines |
| `status` | str | run status |

### 4.2 Artifacts (`aidlc/core/artifacts.py`)

All models extend `Artifact` (`extra="forbid"`). Full list, grouped by phase:

- **Requirements:** `IntakeSummary`, `ClarificationLog{ClarificationItem}`,
  `RequirementsSpec{Requirement(id, kind, title, description,
  acceptance_criteria, priority)}`, `ComplianceNotes(findings, blocking)`,
  `ScopeAssessment(estimate_days, risks, mvp_requirement_ids)`.
- **Design:** `CodebaseMap{ModuleInfo}`, `ArchitectureDecisions{ADR}`,
  `APISpec{Endpoint}`, `DataModel{Entity}`, `ThreatModel{Threat(STRIDE
  category, severity, mitigation)}`, `WorkPlan{WorkItem(id, requirement_ids,
  files_hint, depends_on, acceptance_criteria)}`,
  `TraceabilityMatrix{TraceRow(requirement_id, design_refs, work_item_ids,
  test_ids)}`, `DesignPackage` (bundle of all of the above).
- **Build:** `CodeDiff{FileChange(path, action, content)}`, `EnvReport`,
  `StaticReport{ToolResult}`, `ReviewReport{ReviewComment(severity)}`,
  `PullRequestArtifact`.
- **Test/Eval:** `TestPlan{TestCase(id, requirement_ids, kind, steps,
  expected)}`, `TestResults{TestResult}`, `TriageReport{TriageItem(test_id,
  classification, target_phase, summary)}`, `QualityReport(go,
  coverage_by_requirement, summary, results)`.
- **Deploy:** `ReleaseNotes`, `InfraPlan(changes, strategy)`, `DeployLog`,
  `SoakReport`, `RollbackReport`.
- **Control:** `EvalScorecard(phase, agent, scores, overall, passed,
  feedback)`, `GateDecision(phase, decision, reason, approved_by, approved)`,
  `ChangeRequest(id, source_phase, target_phase, reason, details)`,
  `RunContext`, `Run`.

### 4.3 Agent contract (`aidlc/core/agent.py`)

```python
class BaseAgent:
    name: str                       # trace / log identity
    phase: str
    tier: str = "fast"              # "fast" | "strong" → get_llm(tier)
    system_prompt: str
    output_schema: type[Artifact]
    output_key: str | None          # defaults to snake_case(output_schema)
    relevant_artifacts: tuple[str, ...] = ()   # () = all artifacts

    def user_prompt(self, state) -> str          # subclass supplies
    def run(self, state) -> Artifact             # LLM.structured(...) + trace
    def as_node(self, state) -> dict             # persist to ArtifactStore,
                                                 # return {"artifacts": {key: ...}, "log": [...]}
    def artifacts_json(self, state) -> str       # only relevant_artifacts
```

**Input expectation** of every agent = `intent` + JSON of its
`relevant_artifacts`. **Output expectation** = an instance of `output_schema`,
validated by Pydantic, written to `state.artifacts[output_key]` and to
`runs/<id>/artifacts/<key>.vN.json`.

### 4.4 LLM layer (`aidlc/core/llm.py`)

```python
class LLMClient(Protocol):
    def structured(self, *, system: str, user: str, schema: type[T]) -> T: ...
```

| Provider (`AIDLC_LLM_PROVIDER`) | Class | Behaviour |
|---|---|---|
| `mock` (default) | `MockLLM` | Registry `schema → handler`; deterministic outputs (`aidlc/agents/common.py`). No network. |
| `litellm` | `LiteLLMClient(model)` | Hosted models via LiteLLM; `AIDLC_MODEL` / `AIDLC_MODEL_STRONG` (default `gpt-4o-mini`). |
| `ollama` | `LiteLLMClient("ollama_chat/<model>", api_base=OLLAMA_BASE_URL)` | Local open-source models; defaults `qwen2.5:3b` (fast) / `qwen2.5:7b` (strong). |

`LiteLLMClient.structured` injects the JSON schema into the system prompt,
requests `response_format=json_schema` (falls back to `json_object`), strips
Markdown fences, validates with Pydantic, feeds validation errors back to the
model, `temperature=0`, up to 4 attempts.

### 4.5 Evaluators (`aidlc/core/evals.py`)

`Evaluator(BaseAgent)` — `tier="strong"`, `threshold=0.7`, rubric keys per
phase. `run()`:

1. `deterministic_checks(state) → {key: 0.0|1.0}` (code, no LLM).
2. LLM judge scores the same rubric keys given the evidence.
3. Scores combined; if deterministic is all 1.0 but judge is below threshold,
   the judge is re-asked (≤ 3 judge calls).
4. If the judge raises or returns all-zero scores → deterministic-only
   scorecard with feedback `"LLM judge unavailable; deterministic checks only"`.
5. Emits `EvalScorecard(passed = overall >= threshold)` appended to
   `state.scorecards`.

| Evaluator | Rubric | Deterministic checks |
|---|---|---|
| `RequirementsEvaluator` | completeness, testability, compliance | ≥1 requirement with unique ids; every requirement has acceptance criteria; `compliance_notes.blocking == False` |
| `DesignEvaluator` | traceability, dag | every requirement id appears in traceability; every `depends_on` references a known work item |
| `BuildEvaluator` | implementation, review, static | every work item has a `code_diff_*` and an approved `review_report_*`; `static_report.passed` |
| `TestEvalEvaluator` | quality, coverage | every requirement covered by ≥1 test case; all test results passed |
| `DeployEvaluator` | deployment, soak | `deploy_log.healthy`; `soak_report.healthy` |

### 4.6 Gate policy (`aidlc/core/gate.py`)

`GatePolicy(max_retries=2).decide(scorecard, risk, retries)`:

| Condition | Decision |
|---|---|
| scorecard failed, retries ≥ 2 | `block` |
| scorecard failed, retries < 2 | `review` |
| passed, risk `low`, overall ≥ 0.85 | `auto` (approved_by=`policy`) |
| passed, otherwise (low <0.85, or medium/high risk) | `review` |

`gate_node`: on `review`, if `AIDLC_AUTO_APPROVE=1` → approve automatically;
else `interrupt({phase, reason})` and wait for `{"approved", "by"}`. Approved
deploy gate → `status="completed"`; approved other gate → `running`; rejected →
`blocked`.

---

## 5. Phase 1 — Requirements Analysis

Graph (`aidlc/orchestrators/requirements.py`):
`intake → clarify → author → (compliance ∥ scope) → evaluate → gate`

| Agent | Input artifacts | Output | Expectation |
|---|---|---|---|
| `IntakeContextAgent` (`intake-context`) | `intent` only | `IntakeSummary(summary, affected_components, stakeholders, links)` | Normalise the raw intent: what is being asked, which components/people are affected. |
| `StakeholderClarifierAgent` (`stakeholder-clarifier`) | `intake_summary` | `ClarificationLog(questions[{question, answer, resolved}])` | Surface ambiguities as explicit questions rather than silently assuming. |
| `RequirementsAuthorAgent` (`requirements-author`) | `intake_summary`, `clarification_log` | `RequirementsSpec(title, problem_statement, requirements[REQ-n], out_of_scope, assumptions)` | Testable functional + non-functional requirements, each with acceptance criteria and priority. |
| `DomainComplianceAgent` (`domain-compliance`) | `requirements_spec` | `ComplianceNotes(findings, blocking)` | Privacy / security / regulatory review; `blocking=True` fails the evaluator. |
| `FeasibilityScopeAgent` (`feasibility-scope`) | `requirements_spec` | `ScopeAssessment(estimate_days, risks, mvp_requirement_ids)` | Effort, risks, and an MVP slice. |
| `RequirementsEvaluator` | `requirements_spec`, `compliance_notes` | `EvalScorecard` | See §4.5. |

Exit: `GateDecision(phase="requirements")`.

---

## 6. Phase 2 — Design

Graph (`aidlc/orchestrators/design.py`):
`codebase → adr → (api ∥ data ∥ threat) → work → package → evaluate → gate`

| Agent / node | Input artifacts | Output | Expectation |
|---|---|---|---|
| `CodebaseAnalystAgent` (`codebase-analyst`) | `requirements_spec` (+ `context.repo_path`) | `CodebaseMap(languages, modules, conventions)` | Map the existing code the change must fit into. |
| `SolutionArchitectAgent` (`solution-architect`) | `requirements_spec`, `codebase_map` | `ArchitectureDecisions(adrs[ADR-n])` | Record decisions with context, consequences and rejected alternatives. |
| `APIDataModelerAgent` (`api-data-modeler`) | `requirements_spec`, `architecture_decisions` | `APISpec(endpoints)` → key `api_spec` | Stable endpoint contracts with request/response schemas. |
| `DataModelerAgent` (`data-modeler`) | `requirements_spec`, `architecture_decisions` | `DataModel(entities)` | Entities, fields, relations. |
| `ThreatModelAgent` (`threat-modeler`) | `requirements_spec`, `architecture_decisions` | `ThreatModel(threats[STRIDE])` | Threats with severity and mitigation. |
| `TaskDecomposerAgent` (`task-decomposer`) | all of the above | `WorkPlan(items[WI-n(requirement_ids, depends_on, files_hint, acceptance_criteria)])` | Small, mergeable, dependency-ordered work items that cover every requirement. |
| `package` (code, no LLM) | all design artifacts | `DesignPackage` incl. `TraceabilityMatrix` | Builds `REQ → ADR ids → WI ids → (test_ids filled later)` deterministically. |
| `DesignEvaluator` | `requirements_spec`, `design_package` | `EvalScorecard` | Traceability + DAG validity. |

---

## 7. Phase 3 — Build

Graph (`aidlc/orchestrators/build.py`):
`scaffold → work_items → static_and_tests → integrator → evaluate → gate`

| Agent / node | Input | Output | Expectation |
|---|---|---|---|
| `scaffold` (code) | — | sandbox dirs, `aidlc_generated/__init__.py`, `tests/conftest.py`, `pytest.ini`; `EnvReport(python_version, tools_available, baseline_ok)` | A clean, importable sandbox. (`ScaffoldEnvAgent` class exists but the graph uses this deterministic node.) |
| `work_items` (loop over `design_package.work_plan.items`, topo-sorted by `depends_on`) — per item: | | | |
| &nbsp;&nbsp;`CoderAgent(wi)` (`coder`) | `requirements_spec`, `design_package`, `static_report` | `CodeDiff` → `code_diff_<WI>`; file written to `aidlc_generated/<wi>.py` | Minimal implementation of one work item; path is normalised by the orchestrator. |
| &nbsp;&nbsp;`UnitTestWriterAgent(wi)` (`unit-test-writer`) | same + the implementation diff | `CodeDiff` → `unit_test_diff_<WI>`; `tests/test_<wi>.py` | A small pytest module that actually imports and exercises the generated code. |
| &nbsp;&nbsp;`CodeReviewerAgent(wi)` (`code-reviewer`) | same + impl & test diffs | `ReviewReport(approved, comments[severity])` → `review_report_<WI>` | Correctness / security / acceptance-criteria review; `approved=False` fails the evaluator. |
| `static_and_tests` (code) | sandbox | `StaticReport(tool_results=[ruff, pytest], passed)` | **Real** `ruff check` and `pytest -q` run via `sys.executable` in the sandbox. |
| `IntegratorAgent` (`integrator`) | `design_package`, `static_report`, all diffs | `PullRequestArtifact(branch, title, body, commits, url)` | If `context.repo_path` is set, the repo is copied into the sandbox, diffs applied, committed on branch `aidlc`. The user's repo is never modified. |
| `BuildEvaluator` | `design_package`, `static_report` | `EvalScorecard` | All items implemented + reviewed, static/tests green. |

---

## 8. Phase 4 — Test & Eval

Graph (`aidlc/orchestrators/test_eval.py`):
`plan → integration → e2e → performance → security → triage → quality → evaluate → gate`

| Agent / node | Input | Output | Expectation |
|---|---|---|---|
| `TestPlannerAgent` (`test-planner`) | `requirements_spec`, `design_package` | `TestPlan(cases[T-n(requirement_ids, kind, steps, expected)])`; also fills `traceability.test_ids` | Every requirement mapped to at least one test case. |
| `IntegrationAPITestAgent` (`integration-api-test`) | `requirements_spec`, `design_package`, `test_plan` | `TestResults(kind, results[{test_id, passed, details}])` | Contract/integration verdicts per planned test. |
| `E2ETestAgent` (`e2e-ui-test`) | same | `TestResults` | End-to-end acceptance behaviour. |
| `PerformanceLoadAgent` (`performance-load`) | same | `TestResults` | Performance vs. acceptance criteria. |
| `SecurityTestAgent` (`security-test`) | same | `TestResults` | Authz boundaries, security behaviour. |
| `RegressionTriageAgent` (`regression-triage`) | `test_plan`, `test_results`, `quality_report` | `TriageReport(items[{test_id, classification, target_phase, summary}])` | Classify failures (`product_bug / test_bug / flake / env`) and name the phase to fix them — this drives backward routing. |
| `quality` (code + `QualityAgent` for the summary text only) | `requirements_spec`, `test_plan`, `test_results` | `QualityReport(go, coverage_by_requirement, summary, results)` | `coverage` and `go` are computed deterministically; the LLM only writes prose. |
| `TestEvalEvaluator` | `requirements_spec`, `test_plan`, `test_results`, `quality_report` | `EvalScorecard` | Full coverage and all tests passing. |

Backward routing: after this phase the master reads `triage_report.items`; the
first item with `target_phase` set produces a `ChangeRequest` and re-enters
Design or Build (max 2 hops).

---

## 9. Phase 5 — Deploy

Graph (`aidlc/orchestrators/deploy.py`):
`release → infra → deploy → soak → rollback → evaluate → gate`

| Agent | Input | Output | Expectation |
|---|---|---|---|
| `ReleaseManagerAgent` (`release-manager`) | `design_package`, `quality_report` | `ReleaseNotes(version, highlights, breaking_changes, body)` | Versioned, human-readable release notes. |
| `IaCConfigAgent` (`iac-config`) | `design_package`, `quality_report`, `release_notes` | `InfraPlan(changes, strategy: canary\|blue_green\|rolling)` | Safe infra/config change plan. |
| `DeploymentExecutorAgent` (`deployment-executor`) | `infra_plan`, `release_notes` | `DeployLog(environment, steps, healthy)` | Simulated controlled rollout + health checks. |
| `ObservabilityVerifierAgent` (`observability-verifier`) | `deploy_log` | `SoakReport(duration_minutes, slo_breaches, healthy)` | Post-deploy soak window verdict. |
| `RollbackAgent` (`rollback`) | `deploy_log`, `soak_report` | `RollbackReport(triggered, reason)` | Decide if evidence warrants rollback. |
| `DeployEvaluator` | `quality_report`, `deploy_log`, `soak_report`, `rollback_report` | `EvalScorecard` | Healthy deploy and soak. |

An approved deploy gate sets `status="completed"`. Deployment is
**simulation-only** in this version; no real infrastructure is touched.

---

## 10. Cross-cutting services

| Service | File | Behaviour |
|---|---|---|
| Artifact store | `aidlc/core/store.py` | `$AIDLC_RUNS_DIR/<run_id>/artifacts/<key>.vN.json` + `<key>.latest` pointer; every save is a new version. |
| Tracer | `aidlc/core/tracing.py` | `runs/<run_id>/trace.jsonl` — one line per agent call: `ts, run_id, phase, agent, duration_ms, ok, error`. |
| Checkpointer | `aidlc/orchestrators/master.py` | `SqliteSaver` at `runs/checkpoints.sqlite`; thread id = run id. |
| Static analysis | `aidlc/tools/static_analysis.py` | `python -m ruff check <sandbox>`. |
| Test runner | `aidlc/tools/test_runner.py` | `python -m pytest -q` in sandbox. |
| Sandbox / diffs | `aidlc/orchestrators/base.py::write_changes`, `aidlc/tools/sandbox.py` | Apply `FileChange`s (create/modify/delete) under `runs/<id>/sandbox`. |
| Git tool | `aidlc/tools/git_tool.py` | `copy_repo` (ignores `.git`) and `commit` on branch `aidlc` inside the sandbox. |
| Mock handlers | `aidlc/agents/common.py` | Deterministic outputs per schema so the whole pipeline runs offline in seconds (tests, CI). |

---

## 11. Interfaces

**CLI** (`aidlc/cli.py`, Typer + Rich):

```
aidlc run "<intent>" [--repo PATH] [--risk low|medium|high] [--auto-approve]
                     [--provider mock|litellm|ollama] [--verbose]
aidlc show <run_id>                       # list versioned artifacts
aidlc approve <run_id> --by NAME [--reject]
aidlc serve                               # uvicorn on 127.0.0.1:8000
```

**HTTP API** (`aidlc/services/api.py`, FastAPI):

| Method & path | Purpose |
|---|---|
| `POST /runs` `{intent, context?}` | Start a run in a background thread → `{run_id}` |
| `GET /runs/{id}` | status, phase, gate decisions, scorecards |
| `GET /runs/{id}/artifacts` | artifact keys |
| `GET /runs/{id}/artifacts/{name}` | one artifact |
| `POST /runs/{id}/approve` `{approved, by}` | resume an interrupted gate |

---

## 12. Running with a real open-source LLM

```bash
ollama pull qwen2.5:7b && ollama pull qwen2.5:3b
export AIDLC_LLM_PROVIDER=ollama
export AIDLC_MODEL=qwen2.5:3b            # fast tier
export AIDLC_MODEL_STRONG=qwen2.5:7b     # evaluators / judges
export OLLAMA_BASE_URL=http://127.0.0.1:11434
uv run aidlc run "Add a health endpoint" --auto-approve --verbose
```

Measured on an 8-vCPU, no-GPU VM each agent call took ~3–80 s (outliers
~150 s), so a full run is 30–60 min; a GPU host or hosted open-model endpoint
(`--provider litellm` with any LiteLLM-supported model string) is recommended
for practical use. Small (≤3B) models frequently produce non-runnable code;
the pipeline reports this honestly through `StaticReport`/`BuildEvaluator`
rather than passing.

---

## 13. Known limitations and next steps

- `ScaffoldEnvAgent` is defined but the Build graph uses a deterministic
  scaffold node.
- `DesignEvaluator.dag` checks dependency references, not full cycle detection.
- Test agents (integration/e2e/perf/security) produce LLM-authored verdicts;
  only Build's unit tests are actually executed. Wiring real runners for these
  is the next roadmap step.
- Deployment agents are simulations.
- The API keeps run records in memory; restart loses `GET /runs` listing (the
  SQLite checkpoint and on-disk artifacts persist).
- Roadmap: eval rubrics with golden sets, per-agent model routing/budgets,
  real integration test execution, real deploy adapters, dogfooding on this
  repo.
