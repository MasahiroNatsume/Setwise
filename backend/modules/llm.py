from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import requests

DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-flash-lite"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _extract_text_from_openrouter(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter response missing choices.")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("OpenRouter response missing message.")

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()

    # Some providers can return structured content arrays.
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)

    raise RuntimeError("OpenRouter response does not contain text content.")


class _OpenRouterGenerateResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _OpenRouterModelsClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def generate_content(self, *, model: str, contents: str) -> _OpenRouterGenerateResponse:
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": contents}],
            "temperature": 0.4,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=90,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("OpenRouter response is not valid JSON.") from exc

        text = _extract_text_from_openrouter(data)
        return _OpenRouterGenerateResponse(text=text)


class OpenRouterClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.models = _OpenRouterModelsClient(api_key=api_key, base_url=base_url)


def get_client() -> OpenRouterClient:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    base_url = os.environ.get("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_OPENROUTER_BASE_URL
    return OpenRouterClient(api_key=api_key, base_url=base_url)


@lru_cache(maxsize=1)
def resolve_model_name() -> str:
    preferred = os.environ.get("OPENROUTER_MODEL", "").strip()
    if preferred:
        return preferred
    return DEFAULT_OPENROUTER_MODEL
