from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import DeployLog, InfraPlan, ReleaseNotes, RollbackReport, SoakReport
from aidlc.core.state import AidlcState
from aidlc.agents import common  # noqa: F401


class ReleaseManagerAgent(BaseAgent[ReleaseNotes]):
    name, phase, output_schema = "release-manager", "deploy", ReleaseNotes
    system_prompt = "Prepare versioned release notes and highlight breaking changes."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class IaCConfigAgent(BaseAgent[InfraPlan]):
    name, phase, output_schema = "iac-config", "deploy", InfraPlan
    system_prompt = "Describe safe infrastructure and configuration changes for deployment."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class DeploymentExecutorAgent(BaseAgent[DeployLog]):
    """Simulates deployment; no real cloud calls are made in mock mode."""

    name, phase, output_schema = "deployment-executor", "deploy", DeployLog
    system_prompt = "Simulate a controlled deployment and record health checks."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class ObservabilityVerifierAgent(BaseAgent[SoakReport]):
    """Simulates an observability soak; no real infrastructure is touched."""

    name, phase, output_schema = "observability-verifier", "deploy", SoakReport
    system_prompt = "Simulate a soak window and report SLO breaches."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)


class RollbackAgent(BaseAgent[RollbackReport]):
    """Simulates rollback decisions; no production action is performed."""

    name, phase, output_schema = "rollback", "deploy", RollbackReport
    system_prompt = "Decide whether simulated health evidence requires rollback."

    def build_user_prompt(self, state: AidlcState) -> str:
        return self.artifacts_json(state)
