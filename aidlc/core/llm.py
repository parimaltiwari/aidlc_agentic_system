"""Provider-independent structured LLM clients."""

import json
import os
from collections.abc import Callable
from typing import Protocol, TypeVar

from litellm import completion
from pydantic import BaseModel, ValidationError

from aidlc.core.artifacts import EvalScorecard

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    def structured(self, *, system: str, user: str, schema: type[T]) -> T: ...


class MockLLM:
    registry: dict[type[BaseModel], Callable[[str, str], BaseModel]] = {}

    @classmethod
    def handler(cls, schema: type[T]):
        def decorator(fn: Callable[[str, str], T]):
            cls.registry[schema] = fn
            return fn

        return decorator

    def structured(self, *, system: str, user: str, schema: type[T]) -> T:
        if schema is EvalScorecard:
            return schema.model_validate(
                {
                    "phase": "mock",
                    "agent": "evaluator",
                    "scores": {"quality": 0.85, "coverage": 0.85},
                    "overall": 0.85,
                    "passed": True,
                    "feedback": [],
                }
            )
        if schema not in self.registry:
            raise NotImplementedError(f"No MockLLM handler registered for {schema.__name__}")
        return self.registry[schema](system, user)


class LiteLLMClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def structured(self, *, system: str, user: str, schema: type[T]) -> T:
        prompt = (
            system
            + "\nReturn JSON matching this schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = completion(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                return schema.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                messages.append({"role": "user", "content": f"Validation error: {exc}"})
        raise ValueError(f"LLM output did not validate: {last_error}")


def get_llm(tier: str = "fast") -> LLMClient:
    provider = os.getenv("AIDLC_LLM_PROVIDER", "mock")
    if provider == "litellm":
        model = os.getenv(
            "AIDLC_MODEL_STRONG" if tier == "strong" else "AIDLC_MODEL", "gpt-4o-mini"
        )
        return LiteLLMClient(model)
    return MockLLM()
