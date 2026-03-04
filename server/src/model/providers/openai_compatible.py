"""OpenAI-compatible LLM provider.

Works with any API that implements the OpenAI chat completions format:
  - OpenAI (GPT-4o, o1, ...)
  - DeepSeek (https://api.deepseek.com/v1)
  - OpenRouter (https://openrouter.ai/api/v1)  — access to 200+ models
  - Gemini via OpenAI endpoint (https://generativelanguage.googleapis.com/v1beta/openai)
  - Any self-hosted model via vLLM / Ollama / LM Studio

Configuration in .env:
    OPENAI_API_KEY=<your key>
    OPENAI_BASE_URL=https://api.deepseek.com/v1   # or openrouter, gemini, etc.
    PRIMARY_PROVIDER=openai_compatible
    PRIMARY_MODEL=deepseek-chat
    CHEAP_PROVIDER=openai_compatible
    CHEAP_MODEL=deepseek-chat
"""

import json
from typing import Iterator

import httpx

from src.model.providers.base import LLMProvider, LLMResponse

_DEFAULT_TIMEOUT = 120.0  # seconds


def _error_message_from_response(response: httpx.Response) -> str:
    """Build a user-facing error from an API error response (e.g. OpenRouter 400)."""
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        if isinstance(err, dict) and err.get("message"):
            return f"{response.status_code} {response.reason_phrase}: {err['message']}"
        if isinstance(err, str):
            return f"{response.status_code} {response.reason_phrase}: {err}"
    return f"Client error '{response.status_code} {response.reason_phrase}' for url '{response.url}'"


class OpenAICompatibleProvider(LLMProvider):
    """Synchronous provider for any OpenAI chat-completions-compatible API."""

    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        self._model = model
        self._api_key = api_key
        # Normalise: strip trailing slash so we can always append /chat/completions
        self._base_url = base_url.rstrip("/")
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=_DEFAULT_TIMEOUT,
            )
        return self._client

    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a chat completion request to the configured OpenAI-compatible endpoint.

        The `system` string is prepended as a {"role": "system"} message.
        """
        full_messages = [{"role": "system", "content": system}, *messages]

        payload = {
            "model": self._model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        response = self._get_client().post(
            f"{self._base_url}/chat/completions",
            json=payload,
        )
        if not response.is_success:
            raise ValueError(_error_message_from_response(response))
        data = response.json()

        choices = data.get("choices", [])
        if not choices:
            raise ValueError(
                f"OpenAI-compatible API returned no choices. "
                f"Full response: {data}"
            )

        content = choices[0]["message"]["content"]
        usage = data.get("usage", {})

        return LLMResponse(
            content=content,
            model=data.get("model", self._model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def stream_complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Iterator[str]:
        """Stream a chat completion from the OpenAI-compatible endpoint.

        Yields content deltas as they are received from the API.
        """
        full_messages = [{"role": "system", "content": system}, *messages]
        payload = {
            "model": self._model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        client = self._get_client()

        with client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
        ) as response:
            if not response.is_success:
                raise ValueError(_error_message_from_response(response))
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_piece = delta.get("content")
                if content_piece:
                    yield content_piece
