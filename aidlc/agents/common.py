"""Deterministic mock builders shared by specialist modules."""

import re

from aidlc.core.artifacts import (
    ADR,
    ArchitectureDecisions,
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
    TestCase,
    TestPlan,
    TestResult,
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
    match = re.search(r"WI[-_]\d+", user)
    return match.group(0).replace("_", "-") if match else "WI-1"


def _requirement_ids(user: str) -> list[str]:
    ids = re.findall(r"REQ-\d+", user)
    return list(dict.fromkeys(ids))


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


@MockLLM.handler(RequirementsSpec)
def requirements(_system: str, user: str) -> RequirementsSpec:
    intent = user.split("Intent:", 1)[-1].split(";", 1)[0].split("\n", 1)[0].strip()
    extra = min(2, len(re.findall(r"\band\b|,", intent, flags=re.IGNORECASE)))
    words = [word.strip(".,") for word in intent.split() if word.strip(".,")]
    reqs = []
    for index in range(3 + extra):
        keyword = words[index % len(words)] if words else "workflow"
        reqs.append(
            Requirement(
                id=f"REQ-{index + 1}",
                kind="functional" if index < 3 else "non_functional",
                title=f"{keyword.title()} capability",
                description=f"Support {keyword} as part of the requested intent.",
                acceptance_criteria=[f"The {keyword} behavior is observable and testable."],
                priority="must" if index < 3 else "should",
            )
        )
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


@MockLLM.handler(ArchitectureDecisions)
def architecture_decisions(_system: str, _user: str) -> ArchitectureDecisions:
    return ArchitectureDecisions(adrs=[adr("", "")])


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
def workplan(_system: str, user: str) -> WorkPlan:
    req_ids = _requirement_ids(user) or ["REQ-1", "REQ-2", "REQ-3"]
    items = []
    for offset in range(0, len(req_ids), 2):
        item_number = offset // 2 + 1
        item_id = f"WI-{item_number}"
        items.append(
            WorkItem(
                id=item_id,
                title=f"Implement {', '.join(req_ids[offset : offset + 2])}",
                description="Implement the grouped requirements.",
                requirement_ids=req_ids[offset : offset + 2],
                files_hint=[f"aidlc_generated/{item_id.lower().replace('-', '_')}.py"],
                depends_on=[f"WI-{item_number - 1}"] if item_number > 1 else [],
                acceptance_criteria=["All assigned requirements are implemented."],
            )
        )
    return WorkPlan(items=items)


@MockLLM.handler(CodeDiff)
def code_diff(_system: str, user: str) -> CodeDiff:
    wid = _work_id(user)
    slug = wid.lower().replace("-", "_")
    prompt = user.lower()
    if (
        "write tests" in prompt
        or "test module" in prompt
        or "exactly tests/test_" in prompt
        or "exact test path" in prompt
    ):
        changes = [
            FileChange(
                path=f"tests/test_{slug}.py",
                action="create",
                content=(
                    f"from aidlc_generated.{slug} import {slug}\n\n\n"
                    f'def test_{slug}():\n    assert {slug}() == "{wid} implemented"\n'
                ),
            )
        ]
    else:
        changes = [
            FileChange(
                path=f"aidlc_generated/{slug}.py",
                action="create",
                content=(
                    f'def {slug}() -> str:\n    """Generated implementation for {wid}."""\n'
                    f'    return "{wid} implemented"\n'
                ),
            )
        ]
    return CodeDiff(
        work_item_id=wid,
        changes=changes,
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
def test_plan(_system: str, user: str) -> TestPlan:
    req_ids = _requirement_ids(user) or ["REQ-1", "REQ-2", "REQ-3"]
    return TestPlan(
        cases=[
            TestCase(
                id=f"T-{index}",
                requirement_ids=[req_id],
                kind="unit",
                description=f"Verify {req_id}",
                steps=[f"Exercise {req_id}"],
                expected="Requirement behavior succeeds.",
            )
            for index, req_id in enumerate(req_ids, 1)
        ]
    )


@MockLLM.handler(TestResults)
def test_results(_system: str, user: str) -> TestResults:
    test_ids = list(dict.fromkeys(re.findall(r"T-\d+", user))) or ["T-1"]
    return TestResults(
        kind="integration",
        results=[
            TestResult(test_id=test_id, passed=True, details="mock pass") for test_id in test_ids
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
