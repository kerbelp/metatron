"""The LLM provider interface and the default Anthropic implementation.

The extraction step calls an LLM through this narrow interface so the provider is
configurable (resolved decision: Anthropic Claude default, others droppable in).
Keeping it to a single ``complete(prompt) -> str`` method also keeps a local /
on-prem model viable later without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

DEFAULT_MODEL = "claude-opus-4-8"


class LLMProvider(ABC):
    # Cumulative token usage across calls (providers that know it update these).
    input_tokens: int = 0
    output_tokens: int = 0

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send ``prompt`` to the model and return its text response."""


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.input_tokens = 0
        self.output_tokens = 0
        self._api_key = api_key
        self._client = None  # created lazily so construction needs no key/network

    def complete(self, prompt: str) -> str:
        message = self._get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        self.input_tokens += message.usage.input_tokens
        self.output_tokens += message.usage.output_tokens
        return "".join(
            block.text for block in message.content if block.type == "text"
        )

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client
