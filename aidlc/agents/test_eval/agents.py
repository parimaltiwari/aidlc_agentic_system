from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import QualityReport, TestPlan, TestResults, TriageReport
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class TestPlannerAgent(BaseAgent[TestPlan]):
    name, phase, output_schema = "test-planner", "test_eval", TestPlan

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class IntegrationAPITestAgent(BaseAgent[TestResults]):
    name, phase, output_schema = "integration-api-test", "test_eval", TestResults

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class E2ETestAgent(IntegrationAPITestAgent):
    name = "e2e-ui-test"


class PerformanceLoadAgent(IntegrationAPITestAgent):
    name = "performance-load"


class SecurityTestAgent(IntegrationAPITestAgent):
    name = "security-test"


class RegressionTriageAgent(BaseAgent[TriageReport]):
    name, phase, output_schema = "regression-triage", "test_eval", TriageReport

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class QualityAgent(BaseAgent[QualityReport]):
    name, phase, output_schema = "quality-agent", "test_eval", QualityReport

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
