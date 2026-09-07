from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import (
    ClarificationLog,
    ComplianceNotes,
    IntakeSummary,
    RequirementsSpec,
    ScopeAssessment,
)
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class IntakeContextAgent(BaseAgent[IntakeSummary]):
    name, phase, output_schema = "intake-context", "requirements", IntakeSummary
    system_prompt = "Normalize the product intent into intake context."
    relevant_artifacts = ()

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}"


class StakeholderClarifierAgent(BaseAgent[ClarificationLog]):
    name, phase, output_schema = "stakeholder-clarifier", "requirements", ClarificationLog
    system_prompt = "Identify ambiguity and record focused clarification questions."
    relevant_artifacts = ("intake_summary",)

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; prior: {self.artifacts_json(state)}"


class RequirementsAuthorAgent(BaseAgent[RequirementsSpec]):
    name, phase, output_schema = "requirements-author", "requirements", RequirementsSpec
    system_prompt = "Author testable functional and non-functional requirements from the intent."
    relevant_artifacts = ("intake_summary", "clarification_log")

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; intake: {self.artifacts_json(state)}"


class DomainComplianceAgent(BaseAgent[ComplianceNotes]):
    name, phase, output_schema = "domain-compliance", "requirements", ComplianceNotes
    system_prompt = "Check privacy, security, regulatory, and organizational constraints."
    relevant_artifacts = ("requirements_spec",)

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Review requirements: {self.artifacts_json(state)}"


class FeasibilityScopeAgent(BaseAgent[ScopeAssessment]):
    name, phase, output_schema = "feasibility-scope", "requirements", ScopeAssessment
    system_prompt = "Estimate delivery scope, risks, and a practical MVP slice."
    relevant_artifacts = ("requirements_spec",)

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Assess scope: {self.artifacts_json(state)}"
