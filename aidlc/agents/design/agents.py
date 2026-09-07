from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import ADR, APISpec, CodebaseMap, DataModel, ThreatModel, WorkPlan
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class CodebaseAnalystAgent(BaseAgent[CodebaseMap]):
    name, phase, output_schema = "codebase-analyst", "design", CodebaseMap

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class SolutionArchitectAgent(BaseAgent[ADR]):
    name, phase, output_schema = "solution-architect", "design", ADR

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class APIDataModelerAgent(BaseAgent[APISpec]):
    name, phase, output_schema = "api-data-modeler", "design", APISpec

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class DataModelerAgent(BaseAgent[DataModel]):
    name, phase, output_schema = "data-modeler", "design", DataModel

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class ThreatModelAgent(BaseAgent[ThreatModel]):
    name, phase, output_schema = "threat-modeler", "design", ThreatModel

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class TaskDecomposerAgent(BaseAgent[WorkPlan]):
    name, phase, output_schema = "task-decomposer", "design", WorkPlan

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
