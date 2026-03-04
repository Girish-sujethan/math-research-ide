"""Abstract LLM provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            system: System prompt.
            messages: List of {"role": "user"|"assistant", "content": str} dicts.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            LLMResponse with content and token usage.
        """
        ...

    def stream_complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Iterator[str]:
        """Stream a completion as an iterator of text chunks.

        Default implementation falls back to `complete()` and yields a single chunk.
        Backends that support true streaming should override this method.
        """
        resp = self.complete(system=system, messages=messages, max_tokens=max_tokens, temperature=temperature)
        yield resp.content
