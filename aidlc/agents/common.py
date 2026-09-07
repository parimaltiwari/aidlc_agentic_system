"""Deterministic mock builders shared by specialist modules."""

import re

from aidlc.core.artifacts import (
    ADR,
    APISpec,
    CodeDiff,
    CodebaseMap,
    ComplianceNotes,
    DataModel,
    DeployLog,
    ClarificationLog,
    Endpoint,
    Entity,
    FileChange,
    InfraPlan,
    IntakeSummary,
    PullRequestArtifact,
    QualityReport,
    ReleaseNotes,
    Requirement,
    RequirementsSpec,
    ReviewComment,
    ReviewReport,
    RollbackReport,
    ScopeAssessment,
    SoakReport,
    TestPlan,
    TestResult,
    StaticReport,
    TestResults,
    Threat,
    ThreatModel,
    TraceRow,
    TraceabilityMatrix,
    TriageReport,
    WorkItem,
    WorkPlan,
)
from aidlc.core.llm import MockLLM


def _work_id(user: str) -> str:
    return (
        (
            re.search(r"WI-\d+", user)
            or re.search(r"WI_\d+", user)
            or type("M", (), {"group": lambda s, n: "WI-1"})()
        )
        .group(0)
        .replace("_", "-")
    )


@MockLLM.handler(IntakeSummary)
def intake(_system: str, user: str) -> IntakeSummary:
    return IntakeSummary(
        summary=user[:300],
        affected_components=["user-service"],
        stakeholders=["product", "engineering"],
        links=[],
    )


@MockLLM.handler(ClarificationLog)
def clarification(_system: str, _user: str) -> ClarificationLog:
    return ClarificationLog(questions=[])


@MockLLM.handler(StaticReport)
def static_report(_system: str, _user: str) -> StaticReport:
    return StaticReport(
        tool_results=[
            {
                "tool": "mock-static-analysis",
                "passed": True,
                "output": "Deterministic mock analysis passed.",
            }
        ],
        passed=True,
    )


@MockLLM.handler(RequirementsSpec)
def requirements(_system: str, user: str) -> RequirementsSpec:
    intent = user.split("Intent:", 1)[-1].split("\n", 1)[0].strip()
    reqs = [
        Requirement(
            id="REQ-1",
            kind="functional",
            title="Core workflow",
            description=intent,
            acceptance_criteria=["Given a request, the service returns a successful response."],
            priority="must",
        ),
        Requirement(
            id="REQ-2",
            kind="functional",
            title="Validation",
            description="Validate inputs safely.",
            acceptance_criteria=["Invalid input produces a clear validation error."],
            priority="must",
        ),
        Requirement(
            id="REQ-3",
            kind="non_functional",
            title="Security and reliability",
            description="Protect user data and provide reliable behavior.",
            acceptance_criteria=["Sensitive data is not exposed and errors are handled."],
            priority="should",
        ),
    ]
    return RequirementsSpec(
        title=intent[:80] or "AIDLC feature",
        problem_statement=intent,
        requirements=reqs,
        out_of_scope=["Unrelated product areas"],
        assumptions=["Existing service conventions remain available."],
    )


@MockLLM.handler(ComplianceNotes)
def compliance(_system: str, _user: str) -> ComplianceNotes:
    return ComplianceNotes(
        findings=["Use least privilege and avoid logging secrets."], blocking=False
    )


@MockLLM.handler(ScopeAssessment)
def scope(_system: str, _user: str) -> ScopeAssessment:
    return ScopeAssessment(
        estimate_days=3.0, risks=["Integration assumptions"], mvp_requirement_ids=["REQ-1", "REQ-2"]
    )


@MockLLM.handler(CodebaseMap)
def codebase(_system: str, _user: str) -> CodebaseMap:
    return CodebaseMap(
        languages=["python"], modules=[], conventions=["ruff", "pytest", "small focused modules"]
    )


@MockLLM.handler(ADR)
def adr(_system: str, _user: str) -> ADR:
    return ADR(
        id="ADR-1",
        title="Use service-layer workflow",
        context="Need a maintainable change.",
        decision="Keep the implementation modular and dependency-light.",
        consequences=["Easy testing"],
        alternatives=["Inline implementation"],
    )


@MockLLM.handler(APISpec)
def api(_system: str, _user: str) -> APISpec:
    return APISpec(
        endpoints=[
            Endpoint(
                method="POST",
                path="/workflow",
                description="Run workflow",
                request_schema={"input": "string"},
                response_schema={"ok": "boolean"},
            )
        ]
    )


@MockLLM.handler(DataModel)
def data(_system: str, _user: str) -> DataModel:
    return DataModel(
        entities=[Entity(name="WorkflowRequest", fields={"input": "str"}, relations=[])]
    )


@MockLLM.handler(ThreatModel)
def threat(_system: str, _user: str) -> ThreatModel:
    return ThreatModel(
        threats=[
            Threat(
                category="information_disclosure",
                description="Sensitive output exposure",
                mitigation="Redact secrets and validate authorization.",
                severity="medium",
            )
        ]
    )


@MockLLM.handler(WorkPlan)
def workplan(_system: str, _user: str) -> WorkPlan:
    return WorkPlan(
        items=[
            WorkItem(
                id="WI-1",
                title="Implement workflow",
                description="Implement core workflow.",
                requirement_ids=["REQ-1", "REQ-2"],
                files_hint=["aidlc_generated/workflow.py"],
                depends_on=[],
                acceptance_criteria=["Core workflow works."],
            ),
            WorkItem(
                id="WI-2",
                title="Harden workflow",
                description="Add security and reliability handling.",
                requirement_ids=["REQ-3"],
                files_hint=["aidlc_generated/hardening.py"],
                depends_on=["WI-1"],
                acceptance_criteria=["Errors are safe."],
            ),
        ]
    )


@MockLLM.handler(CodeDiff)
def code_diff(_system: str, user: str) -> CodeDiff:
    wid = _work_id(user)
    slug = wid.lower().replace("-", "_")
    return CodeDiff(
        work_item_id=wid,
        changes=[
            FileChange(
                path=f"aidlc_generated/{slug}.py",
                action="create",
                content=f'def {slug}() -> str:\n    """Generated implementation for {wid}."""\n    return "{wid} implemented"\n',
            ),
            FileChange(
                path=f"tests/test_{slug}.py",
                action="create",
                content=(
                    f"from aidlc_generated.{slug} import {slug}\n\n\n"
                    f'def test_{slug}():\n    assert {slug}() == "{wid} implemented"\n'
                ),
            ),
        ],
        commit_message=f"Implement {wid}",
    )


@MockLLM.handler(ReviewReport)
def review(_system: str, user: str) -> ReviewReport:
    wid = _work_id(user)
    return ReviewReport(
        work_item_id=wid,
        approved=True,
        comments=[
            ReviewComment(
                path=f"aidlc_generated/{wid.lower().replace('-', '_')}.py",
                line=1,
                severity="nit",
                comment="Consider a domain-specific name.",
            )
        ],
    )


@MockLLM.handler(PullRequestArtifact)
def pr(_system: str, _user: str) -> PullRequestArtifact:
    return PullRequestArtifact(
        branch="aidlc/mock",
        title="AIDLC generated changes",
        body="Generated by deterministic AIDLC mock.",
        commits=[],
        url=None,
    )


@MockLLM.handler(TestPlan)
def test_plan(_system: str, _user: str) -> TestPlan:
    return TestPlan(
        cases=[
            {
                "id": "T-1",
                "requirement_ids": ["REQ-1"],
                "kind": "unit",
                "description": "Core workflow test",
                "steps": ["Call workflow"],
                "expected": "Success",
            },
            {
                "id": "T-2",
                "requirement_ids": ["REQ-2", "REQ-3"],
                "kind": "integration",
                "description": "Validation and security test",
                "steps": ["Send invalid input"],
                "expected": "Safe error",
            },
        ]
    )


@MockLLM.handler(TestResults)
def test_results(_system: str, _user: str) -> TestResults:
    return TestResults(
        kind="integration",
        results=[
            TestResult(test_id="T-1", passed=True, details="mock pass"),
            TestResult(test_id="T-2", passed=True, details="mock pass"),
        ],
    )


@MockLLM.handler(TriageReport)
def triage(_system: str, _user: str) -> TriageReport:
    return TriageReport(items=[])


@MockLLM.handler(QualityReport)
def quality(_system: str, _user: str) -> QualityReport:
    return QualityReport(
        go=True,
        coverage_by_requirement={"REQ-1": True, "REQ-2": True, "REQ-3": True},
        summary="All deterministic mock tests passed.",
        results=[],
    )


@MockLLM.handler(ReleaseNotes)
def release(_system: str, _user: str) -> ReleaseNotes:
    return ReleaseNotes(
        version="0.1.0", highlights=["Generated release"], breaking_changes=[], body="Mock release."
    )


@MockLLM.handler(InfraPlan)
def infra(_system: str, _user: str) -> InfraPlan:
    return InfraPlan(changes=["Simulated configuration update"], strategy="rolling")


@MockLLM.handler(DeployLog)
def deploy(_system: str, _user: str) -> DeployLog:
    return DeployLog(
        environment="simulation",
        steps=["Validate artifact", "Simulate deployment", "Health check"],
        healthy=True,
    )


@MockLLM.handler(SoakReport)
def soak(_system: str, _user: str) -> SoakReport:
    return SoakReport(duration_minutes=1, slo_breaches=[], healthy=True)


@MockLLM.handler(RollbackReport)
def rollback(_system: str, _user: str) -> RollbackReport:
    return RollbackReport(triggered=False, reason=None)


def design_package_parts() -> tuple[
    CodebaseMap, list[ADR], APISpec, DataModel, ThreatModel, WorkPlan, TraceabilityMatrix
]:
    cb = codebase("", "")
    plans = workplan("", "")
    rows = [
        TraceRow(
            requirement_id=f"REQ-{i}",
            design_refs=["ADR-1"],
            work_item_ids=["WI-1" if i < 3 else "WI-2"],
            test_ids=["T-1", "T-2"],
        )
        for i in range(1, 4)
    ]
    return (
        cb,
        [adr("", "")],
        api("", ""),
        data("", ""),
        threat("", ""),
        plans,
        TraceabilityMatrix(rows=rows),
    )
