from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import QualityReport, TestPlan, TestResults, TriageReport
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class TestPlannerAgent(BaseAgent[TestPlan]):
    name, phase, output_schema = "test-planner", "test_eval", TestPlan
    system_prompt = "Create a requirement-to-test matrix covering every requirement."
    relevant_artifacts = ("requirements_spec", "design_package")

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class IntegrationAPITestAgent(BaseAgent[TestResults]):
    name, phase, output_schema = "integration-api-test", "test_eval", TestResults
    system_prompt = "Run deterministic integration and contract checks."
    relevant_artifacts = ("requirements_spec", "design_package", "test_plan")

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class E2ETestAgent(IntegrationAPITestAgent):
    name = "e2e-ui-test"
    system_prompt = "Exercise end-to-end acceptance behavior deterministically."


class PerformanceLoadAgent(IntegrationAPITestAgent):
    name = "performance-load"
    system_prompt = "Assess performance behavior against available acceptance criteria."


class SecurityTestAgent(IntegrationAPITestAgent):
    name = "security-test"
    system_prompt = "Check security-sensitive behavior and authorization boundaries."


class RegressionTriageAgent(BaseAgent[TriageReport]):
    name, phase, output_schema = "regression-triage", "test_eval", TriageReport
    system_prompt = "Classify failures and route actionable change requests to design or build."
    relevant_artifacts = ("test_plan", "test_results", "quality_report")

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class QualityAgent(BaseAgent[QualityReport]):
    name, phase, output_schema = "quality-agent", "test_eval", QualityReport
    system_prompt = "Summarize quality evidence while deterministic checks decide go or no-go."
    relevant_artifacts = ("requirements_spec", "test_plan", "test_results")

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
