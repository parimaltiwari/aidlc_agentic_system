from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import CodeDiff, PullRequestArtifact, ReviewReport, StaticReport
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class ScaffoldEnvAgent(BaseAgent[StaticReport]):
    name, phase, output_schema = "scaffold-env", "build", StaticReport

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class CoderAgent(BaseAgent[CodeDiff]):
    name, phase, output_schema = "coder", "build", CodeDiff

    def __init__(self, work_item_id: str):
        self.work_item_id = work_item_id

    @property
    def output_key(self):
        return f"code_diff_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Work item {self.work_item_id}; {self.artifacts_json(state)}"


class UnitTestWriterAgent(CoderAgent):
    name = "unit-test-writer"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Work item {self.work_item_id}; write tests; {self.artifacts_json(state)}"


class StaticAnalysisAgent(BaseAgent[StaticReport]):
    name, phase, output_schema = "static-analysis", "build", StaticReport

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class CodeReviewerAgent(BaseAgent[ReviewReport]):
    name, phase, output_schema = "code-reviewer", "build", ReviewReport

    def __init__(self, work_item_id: str):
        self.work_item_id = work_item_id

    @property
    def output_key(self):
        return f"review_report_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Review {self.work_item_id}; {self.artifacts_json(state)}"


class IntegratorAgent(BaseAgent[PullRequestArtifact]):
    name, phase, output_schema = "integrator", "build", PullRequestArtifact

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
