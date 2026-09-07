from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import (
    APISpec,
    ArchitectureDecisions,
    CodebaseMap,
    DataModel,
    ThreatModel,
    WorkPlan,
)
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class CodebaseAnalystAgent(BaseAgent[CodebaseMap]):
    name, phase, output_schema = "codebase-analyst", "design", CodebaseMap
    system_prompt = "Map modules, languages, dependencies, and repository conventions."
    relevant_artifacts = ("requirements_spec",)

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; {self.artifacts_json(state)}"


class SolutionArchitectAgent(BaseAgent[ArchitectureDecisions]):
    name, phase, output_schema = "solution-architect", "design", ArchitectureDecisions
    system_prompt = "Choose a maintainable architecture and record explicit ADR decisions."
    relevant_artifacts = ("requirements_spec", "codebase_map")

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; {self.artifacts_json(state)}"


class APIDataModelerAgent(BaseAgent[APISpec]):
    name, phase, output_schema = "api-data-modeler", "design", APISpec
    system_prompt = "Define stable API endpoints and request/response schemas."
    relevant_artifacts = ("requirements_spec", "architecture_decisions")

    @property
    def output_key(self):
        return "api_spec"

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; {self.artifacts_json(state)}"


class DataModelerAgent(BaseAgent[DataModel]):
    name, phase, output_schema = "data-modeler", "design", DataModel
    system_prompt = "Define entities, fields, and relationships for the feature."
    relevant_artifacts = ("requirements_spec", "architecture_decisions")

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; {self.artifacts_json(state)}"


class ThreatModelAgent(BaseAgent[ThreatModel]):
    name, phase, output_schema = "threat-modeler", "design", ThreatModel
    system_prompt = "Identify STRIDE threats and concrete mitigations."
    relevant_artifacts = ("requirements_spec", "architecture_decisions")

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; {self.artifacts_json(state)}"


class TaskDecomposerAgent(BaseAgent[WorkPlan]):
    name, phase, output_schema = "task-decomposer", "design", WorkPlan
    system_prompt = "Decompose requirements into ordered, independently mergeable work items."
    relevant_artifacts = (
        "requirements_spec",
        "codebase_map",
        "architecture_decisions",
        "api_spec",
        "data_model",
        "threat_model",
    )

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Intent: {state.get('intent', '')}; {self.artifacts_json(state)}"
