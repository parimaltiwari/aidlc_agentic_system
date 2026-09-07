"""Provider-independent structured LLM clients."""

import json
import os
import re
from collections.abc import Callable
from typing import Protocol, TypeVar

from litellm import completion
from pydantic import BaseModel, ValidationError

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
        if schema not in self.registry:
            raise NotImplementedError(f"No MockLLM handler registered for {schema.__name__}")
        return self.registry[schema](system, user)


class LiteLLMClient:
    def __init__(self, model: str, api_base: str | None = None) -> None:
        self.model = model
        self.api_base = api_base

    def structured(self, *, system: str, user: str, schema: type[T]) -> T:
        schema_json = schema.model_json_schema()
        prompt = system + "\nReturn JSON matching this schema:\n" + json.dumps(schema_json)
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        schema_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema_json},
        }
        json_object_format = {"type": "json_object"}
        use_schema = True
        for _attempt in range(4):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "response_format": schema_format if use_schema else json_object_format,
                    "temperature": 0,
                    "max_tokens": 2048,
                }
                if self.api_base:
                    kwargs["api_base"] = self.api_base
                response = completion(**kwargs)
                content = response.choices[0].message.content
                if content is None:
                    raise ValueError("LLM returned an empty response")
                content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content.strip())
                return schema.model_validate_json(content)
            except (ValidationError, ValueError, TypeError) as exc:
                last_error = exc
                messages.append({"role": "user", "content": f"Validation error: {exc}"})
            except Exception as exc:
                use_schema = False
                last_error = exc
                messages.append({"role": "user", "content": f"Validation error: {exc}"})
        raise ValueError(f"LLM output did not validate: {last_error}")


def get_llm(tier: str = "fast") -> LLMClient:
    provider = os.getenv("AIDLC_LLM_PROVIDER", "mock")
    if provider in {"litellm", "ollama"}:
        default_model = "qwen2.5:7b" if tier == "strong" else "qwen2.5:3b"
        model = os.getenv(
            "AIDLC_MODEL_STRONG" if tier == "strong" else "AIDLC_MODEL",
            default_model if provider == "ollama" else "gpt-4o-mini",
        )
        if provider == "ollama":
            return LiteLLMClient(
                f"ollama_chat/{model}",
                api_base=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            )
        return LiteLLMClient(model)
    return MockLLM()
