import json

from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import CodeDiff, EnvReport, PullRequestArtifact, ReviewReport
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class ScaffoldEnvAgent(BaseAgent[EnvReport]):
    name, phase, output_schema = "scaffold-env", "build", EnvReport
    system_prompt = "Inspect the Python sandbox and report available tools and baseline health."
    relevant_artifacts = ("design_package",)

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class CoderAgent(BaseAgent[CodeDiff]):
    name, phase, output_schema = "coder", "build", CodeDiff
    system_prompt = "Implement one focused work item with a minimal, testable code change."
    relevant_artifacts = ("requirements_spec", "design_package", "static_report")

    def __init__(self, work_item_id: str):
        self.work_item_id = work_item_id

    @property
    def output_key(self):
        return f"code_diff_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        items = (
            state.get("artifacts", {})
            .get("design_package", {})
            .get("work_plan", {})
            .get("items", [])
        )
        item = next((item for item in items if item["id"] == self.work_item_id), {})
        path = f"aidlc_generated/{self.work_item_id.lower().replace('-', '_')}.py"
        return (
            f"Work item: {item}. Implement only this item. The implementation MUST be in "
            f"exactly {path}. Return a CodeDiff with that path. "
            f"Relevant artifacts: {self.artifacts_json(state)}"
        )


class UnitTestWriterAgent(CoderAgent):
    name = "unit-test-writer"
    system_prompt = "Write a small passing pytest module for the assigned work item."
    relevant_artifacts = ("requirements_spec", "design_package", "static_report")

    @property
    def output_key(self):
        return f"unit_test_diff_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        items = (
            state.get("artifacts", {})
            .get("design_package", {})
            .get("work_plan", {})
            .get("items", [])
        )
        item = next((item for item in items if item["id"] == self.work_item_id), {})
        slug = self.work_item_id.lower().replace("-", "_")
        code_diff = state.get("artifacts", {}).get(f"code_diff_{slug}", {})
        return (
            f"Work item: {item}. Write a passing pytest module for the implementation. The test "
            f"MUST be in exactly tests/test_{slug}.py and import from aidlc_generated.{slug}. "
            f"Return a CodeDiff with that exact test path. Relevant artifacts: "
            f"{self.artifacts_json(state)}; implementation: {json.dumps(code_diff, sort_keys=True)}"
        )


class CodeReviewerAgent(BaseAgent[ReviewReport]):
    name, phase, output_schema = "code-reviewer", "build", ReviewReport
    system_prompt = "Review the work item for correctness, security, and acceptance criteria."
    relevant_artifacts = (
        "requirements_spec",
        "design_package",
        "static_report",
        "review_report",
    )

    def __init__(self, work_item_id: str):
        self.work_item_id = work_item_id

    @property
    def output_key(self):
        return f"review_report_{self.work_item_id.lower().replace('-', '_')}"

    def build_user_prompt(self, state: AidlcState) -> str:
        slug = self.work_item_id.lower().replace("-", "_")
        code_diff = state.get("artifacts", {}).get(f"code_diff_{slug}", {})
        test_diff = state.get("artifacts", {}).get(f"unit_test_diff_{slug}", {})
        return (
            f"Review work item {self.work_item_id}, including any static/pytest failures in "
            f"static_report. Approve only if implementation and tests are sound. "
            f"Relevant artifacts: {self.artifacts_json(state)}; implementation: "
            f"{json.dumps(code_diff, sort_keys=True)}; tests: {json.dumps(test_diff, sort_keys=True)}"
        )


class IntegratorAgent(BaseAgent[PullRequestArtifact]):
    name, phase, output_schema = "integrator", "build", PullRequestArtifact
    system_prompt = "Assemble approved changes into a mergeable pull-request artifact."
    relevant_artifacts = ("design_package", "static_report")

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
