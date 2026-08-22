"""Claude API client wrapper.

One narrow surface for the whole harness: ``LLM.structured()`` sends a prompt
and returns a dict validated server-side against a JSON schema (structured
outputs via ``output_config.format``). Everything model-specific lives here:

- model: ``claude-opus-5`` by default; thinking is on by default (adaptive),
  so no ``thinking`` parameter is sent, and depth is controlled with
  ``output_config.effort``.
- refusal handling: safety classifiers can decline a request with a normal
  HTTP 200 and ``stop_reason: "refusal"``. Server-side fallbacks
  (``fallbacks: "default"``, beta) are enabled by default so a declined
  request is transparently re-served by Anthropic's recommended fallback
  model; if the whole chain refuses we raise ``RefusalError``.
"""

from __future__ import annotations

import json
from typing import Protocol

from .config import Config
from .errors import (
    LLMError,
    RefusalError,
    StructuredOutputError,
    TruncatedOutputError,
)

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM(Protocol):
    """What the harness needs from a language model."""

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict,
        max_tokens: int | None = None,
    ) -> dict:
        """Return a JSON object conforming to ``schema``."""
        ...


class AnthropicLLM:
    """Production implementation backed by the Anthropic Messages API."""

    def __init__(self, config: Config):
        import anthropic  # deferred so the package imports without the SDK

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self._config = config

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict,
        max_tokens: int | None = None,
    ) -> dict:
        anthropic = self._anthropic
        request: dict = {
            "model": self._config.model,
            "max_tokens": max_tokens or self._config.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "effort": self._config.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if self._config.enable_fallbacks:
            request["betas"] = [_FALLBACK_BETA]
            # Scalar "default" mode: the API picks the recommended fallback
            # model per refusal category. Sent via extra_body because older
            # SDK typings only cover the array form of `fallbacks`.
            request["extra_body"] = {"fallbacks": "default"}

        try:
            if self._config.enable_fallbacks:
                response = self._client.beta.messages.create(**request)
            else:
                response = self._client.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "Authentication failed. Set ANTHROPIC_API_KEY or run `ant auth login`."
            ) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Unknown model {self._config.model!r}: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach the Claude API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise RefusalError(
                "The model declined this request (safety classifiers). "
                "Rephrase the topic or question and try again."
            )
        if response.stop_reason == "max_tokens":
            raise TruncatedOutputError(
                "The model response was truncated at the token ceiling; "
                "retry or raise Config.max_tokens."
            )

        text = next(
            (block.text for block in response.content if block.type == "text"),
            None,
        )
        if text is None:
            raise StructuredOutputError("Response contained no text block.")
        return parse_structured_text(text)


def parse_structured_text(text: str) -> dict:
    """Parse a structured-output text block into a dict.

    With ``output_config.format`` the API guarantees schema-valid JSON, but we
    stay defensive so a malformed reply surfaces as a harness error rather
    than a stack trace mid-lesson.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StructuredOutputError(
            f"Expected a JSON object, got {type(data).__name__}."
        )
    return data
