"""Provider selection is explicit; construction and imports never use the network."""

import json
import os
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from shared.schemas import StrictModel

T = TypeVar("T", bound=BaseModel)


class ProviderConfigurationError(ValueError):
    pass


class ModelConfig(StrictModel):
    model: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 30.0


class MockChatModel:
    """A deterministic structured responder; no random state or external clients."""

    mode = "mock"

    def __init__(self, responder: Callable[[str], Any] | None = None):
        self.responder = responder

    def invoke(self, prompt: str) -> str:
        value = self.responder(prompt) if self.responder else json.loads(prompt)
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    def invoke_structured(self, prompt: str, schema: type[T]) -> T:
        return schema.model_validate_json(self.invoke(prompt))


class OpenAICompatibleModel:
    """Opt-in adapter using the standard library; requests occur only in invoke."""

    mode = "openai"

    def __init__(self, config: ModelConfig):
        if not config.model:
            raise ProviderConfigurationError("real providers require an explicit model")
        if not os.environ.get(config.api_key_env):
            raise ProviderConfigurationError(f"missing credential variable {config.api_key_env}")
        if not config.base_url.startswith("https://"):
            raise ProviderConfigurationError("provider endpoint must use HTTPS")
        self.config = config

    def invoke_structured(self, prompt: str, schema: type[T]) -> T:
        # Recheck opt-in at invocation so a retained client cannot bypass offline mode.
        if os.environ.get("LLM_PROVIDER", "mock").lower() != "openai":
            raise ProviderConfigurationError("real invocation requires LLM_PROVIDER=openai")
        import urllib.request

        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
        }
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + os.environ[self.config.api_key_env],
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
            data = json.load(response)
        return schema.model_validate_json(data["choices"][0]["message"]["content"])


def get_model(config: ModelConfig | None = None, responder=None):
    provider = os.environ.get("LLM_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return MockChatModel(responder)
    if provider == "openai":
        return OpenAICompatibleModel(config or ModelConfig())
    raise ProviderConfigurationError(f"unsupported LLM_PROVIDER: {provider!r}")