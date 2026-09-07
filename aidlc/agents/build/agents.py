from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import CodeDiff, EnvReport, PullRequestArtifact, ReviewReport
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class ScaffoldEnvAgent(BaseAgent[EnvReport]):
    name, phase, output_schema = "scaffold-env", "build", EnvReport
    system_prompt = "Inspect the Python sandbox and report available tools and baseline health."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class CoderAgent(BaseAgent[CodeDiff]):
    name, phase, output_schema = "coder", "build", CodeDiff
    system_prompt = "Implement one focused work item with a minimal, testable code change."

    def __init__(self, work_item_id: str):
        self.work_item_id = work_item_id

    @property
    def output_key(self):
        return f"code_diff_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Work item {self.work_item_id}; {self.artifacts_json(state)}"


class UnitTestWriterAgent(CoderAgent):
    name = "unit-test-writer"
    system_prompt = "Write a small passing pytest module for the assigned work item."

    @property
    def output_key(self):
        return f"unit_test_diff_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Work item {self.work_item_id}; write tests; {self.artifacts_json(state)}"


class CodeReviewerAgent(BaseAgent[ReviewReport]):
    name, phase, output_schema = "code-reviewer", "build", ReviewReport
    system_prompt = "Review the work item for correctness, security, and acceptance criteria."

    def __init__(self, work_item_id: str):
        self.work_item_id = work_item_id

    @property
    def output_key(self):
        return f"review_report_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Review {self.work_item_id}; {self.artifacts_json(state)}"


class IntegratorAgent(BaseAgent[PullRequestArtifact]):
    name, phase, output_schema = "integrator", "build", PullRequestArtifact
    system_prompt = "Assemble approved changes into a mergeable pull-request artifact."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
