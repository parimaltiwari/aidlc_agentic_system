"""Typed artifacts exchanged by AIDLC agents."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(Artifact):
    id: str
    kind: Literal["functional", "non_functional"]
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: Literal["must", "should", "could"]


class IntakeSummary(Artifact):
    summary: str
    affected_components: list[str]
    stakeholders: list[str]
    links: list[str]


class ClarificationItem(Artifact):
    question: str
    answer: str | None
    resolved: bool


class ClarificationLog(Artifact):
    questions: list[ClarificationItem]


class RequirementsSpec(Artifact):
    title: str
    problem_statement: str
    requirements: list[Requirement]
    out_of_scope: list[str]
    assumptions: list[str]


class ComplianceNotes(Artifact):
    findings: list[str]
    blocking: bool


class ScopeAssessment(Artifact):
    estimate_days: float
    risks: list[str]
    mvp_requirement_ids: list[str]


class ModuleInfo(Artifact):
    path: str
    purpose: str
    depends_on: list[str]


class CodebaseMap(Artifact):
    languages: list[str]
    modules: list[ModuleInfo]
    conventions: list[str]


class ADR(Artifact):
    id: str
    title: str
    context: str
    decision: str
    consequences: list[str]
    alternatives: list[str]


class ArchitectureDecisions(Artifact):
    adrs: list[ADR]


class Endpoint(Artifact):
    method: str
    path: str
    description: str
    request_schema: dict
    response_schema: dict


class APISpec(Artifact):
    endpoints: list[Endpoint]


class Entity(Artifact):
    name: str
    fields: dict[str, str]
    relations: list[str]


class DataModel(Artifact):
    entities: list[Entity]


class Threat(Artifact):
    category: Literal[
        "spoofing",
        "tampering",
        "repudiation",
        "information_disclosure",
        "denial_of_service",
        "elevation_of_privilege",
    ]
    description: str
    mitigation: str
    severity: Literal["low", "medium", "high"]


class ThreatModel(Artifact):
    threats: list[Threat]


class WorkItem(Artifact):
    id: str
    title: str
    description: str
    requirement_ids: list[str]
    files_hint: list[str]
    depends_on: list[str]
    acceptance_criteria: list[str]


class WorkPlan(Artifact):
    items: list[WorkItem]


class TraceRow(Artifact):
    requirement_id: str
    design_refs: list[str]
    work_item_ids: list[str]
    test_ids: list[str]


class TraceabilityMatrix(Artifact):
    rows: list[TraceRow]


class DesignPackage(Artifact):
    codebase_map: CodebaseMap
    adrs: list[ADR]
    api_spec: APISpec
    data_model: DataModel
    threat_model: ThreatModel
    work_plan: WorkPlan
    traceability: TraceabilityMatrix


class FileChange(Artifact):
    path: str
    action: Literal["create", "modify", "delete"]
    content: str | None


class CodeDiff(Artifact):
    work_item_id: str
    changes: list[FileChange]
    commit_message: str


class EnvReport(Artifact):
    python_version: str
    tools_available: list[str]
    baseline_ok: bool


class ToolResult(Artifact):
    tool: str
    passed: bool
    output: str


class StaticReport(Artifact):
    tool_results: list[ToolResult]
    passed: bool


class ReviewComment(Artifact):
    path: str
    line: int | None
    severity: Literal["nit", "minor", "major", "blocker"]
    comment: str


class ReviewReport(Artifact):
    work_item_id: str
    approved: bool
    comments: list[ReviewComment]


class PullRequestArtifact(Artifact):
    branch: str
    title: str
    body: str
    commits: list[str]
    url: str | None


class TestCase(Artifact):
    id: str
    requirement_ids: list[str]
    kind: Literal["unit", "integration", "e2e", "perf", "security"]
    description: str
    steps: list[str]
    expected: str


class TestPlan(Artifact):
    cases: list[TestCase]


class TestResult(Artifact):
    test_id: str
    passed: bool
    details: str


class TestResults(Artifact):
    kind: str
    results: list[TestResult]


class TriageItem(Artifact):
    test_id: str
    classification: Literal["product_bug", "test_bug", "flake", "env"]
    target_phase: Literal["design", "build"] | None
    summary: str


class TriageReport(Artifact):
    items: list[TriageItem]


class QualityReport(Artifact):
    go: bool
    coverage_by_requirement: dict[str, bool]
    summary: str
    results: list[TestResults]


class ReleaseNotes(Artifact):
    version: str
    highlights: list[str]
    breaking_changes: list[str]
    body: str


class InfraPlan(Artifact):
    changes: list[str]
    strategy: Literal["canary", "blue_green", "rolling"]


class DeployLog(Artifact):
    environment: str
    steps: list[str]
    healthy: bool


class SoakReport(Artifact):
    duration_minutes: int
    slo_breaches: list[str]
    healthy: bool


class RollbackReport(Artifact):
    triggered: bool
    reason: str | None


class EvalScorecard(Artifact):
    phase: str
    agent: str
    scores: dict[str, float]
    overall: float
    passed: bool
    feedback: list[str]


class GateDecision(Artifact):
    phase: str
    decision: Literal["auto", "review", "block"]
    reason: str
    approved_by: str | None
    approved: bool | None


class ChangeRequest(Artifact):
    id: str
    source_phase: str
    target_phase: str
    reason: str
    details: list[str]


class RunContext(Artifact):
    repo_path: str | None
    target_env: str
    risk_level: Literal["low", "medium", "high"]
    budget_usd: float
    stakeholders: list[str]


class Run(Artifact):
    id: str
    intent: str
    context: RunContext
    status: Literal["running", "awaiting_approval", "completed", "blocked", "failed"]
    phase: str
    created_at: str
