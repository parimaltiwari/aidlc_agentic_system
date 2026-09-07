"""Base implementation for structured AIDLC agents."""

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from aidlc.core.llm import get_llm
from aidlc.core.state import AidlcState
from aidlc.core.store import ArtifactStore
from aidlc.core.tracing import Tracer

T = TypeVar("T")


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class BaseAgent(Generic[T], ABC):
    name = "base"
    phase = "unknown"
    tier = "fast"
    output_schema: type[T]
    system_prompt = "Return a valid structured artifact."

    @property
    def output_key(self) -> str:
        return _snake(self.output_schema.__name__)

    @abstractmethod
    def build_user_prompt(self, state: AidlcState) -> str:
        raise NotImplementedError

    def run(self, state: AidlcState) -> T:
        started = time.perf_counter()
        tracer = Tracer(state.get("run_id", "local"))
        try:
            result = get_llm(self.tier).structured(
                system=self.system_prompt,
                user=self.build_user_prompt(state),
                schema=self.output_schema,
            )
            tracer.record(self.name, self.phase, time.perf_counter() - started, True)
            return result
        except Exception as exc:
            tracer.record(self.name, self.phase, time.perf_counter() - started, False, str(exc))
            raise

    def as_node(self):
        def node(state: AidlcState) -> dict:
            result = self.run(state)
            ArtifactStore(state.get("run_id", "local")).save(self.output_key, result)
            return {
                "artifacts": {self.output_key: result.model_dump(mode="json")},
                "log": [f"{self.phase}:{self.name} produced {self.output_key}"],
                "phase": self.phase,
            }

        return node

    @staticmethod
    def artifacts_json(state: AidlcState) -> str:
        return json.dumps(state.get("artifacts", {}), sort_keys=True)
