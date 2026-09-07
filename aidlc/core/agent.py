"""Base implementation for structured AIDLC agents."""

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from aidlc.core.llm import get_llm
from aidlc.core.state import AidlcState
from aidlc.storage.factory import get_artifact_store, get_tracer

T = TypeVar("T")


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class BaseAgent(Generic[T], ABC):
    name = "base"
    phase = "unknown"
    tier = "fast"
    output_schema: type[T]
    system_prompt = "Return a valid structured artifact."
    relevant_artifacts: tuple[str, ...] = ()

    @property
    def output_key(self) -> str:
        return _snake(self.output_schema.__name__)

    @abstractmethod
    def build_user_prompt(self, state: AidlcState) -> str:
        raise NotImplementedError

    def run(self, state: AidlcState) -> T:
        started = time.perf_counter()
        llm = get_llm(self.tier)
        tracer = get_tracer(state.get("run_id", "local"))
        try:
            result = llm.structured(
                system=self.system_prompt,
                user=self.build_user_prompt(state),
                schema=self.output_schema,
            )
            tracer.record(
                self.name,
                self.phase,
                time.perf_counter() - started,
                True,
                model=getattr(llm, "model", None),
                work_item_id=getattr(self, "work_item_id", None),
            )
            return result
        except Exception as exc:
            tracer.record(
                self.name,
                self.phase,
                time.perf_counter() - started,
                False,
                str(exc),
                model=getattr(llm, "model", None),
                work_item_id=getattr(self, "work_item_id", None),
            )
            raise

    def as_node(self):
        def node(state: AidlcState) -> dict:
            result = self.run(state)
            get_artifact_store(state.get("run_id", "local")).save(self.output_key, result)
            return {
                "artifacts": {self.output_key: result.model_dump(mode="json")},
                "log": [f"{self.phase}:{self.name} produced {self.output_key}"],
            }

        return node

    def artifacts_json(self, state: AidlcState) -> str:
        artifacts = state.get("artifacts", {})
        if self.relevant_artifacts:
            artifacts = {key: artifacts[key] for key in self.relevant_artifacts if key in artifacts}
        return json.dumps(artifacts, sort_keys=True)
