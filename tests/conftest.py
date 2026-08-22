"""Shared test doubles: a scripted LLM and a scripted IO."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@dataclass
class LLMCall:
    system: str
    prompt: str
    schema: dict


class FakeLLM:
    """Returns queued structured responses in order; records every call."""

    def __init__(self, responses: list[dict] | None = None):
        self.responses: list[dict] = list(responses or [])
        self.calls: list[LLMCall] = []

    def push(self, *responses: dict) -> "FakeLLM":
        self.responses.extend(responses)
        return self

    def structured(self, *, system, prompt, schema, max_tokens=None) -> dict:
        self.calls.append(LLMCall(system=system, prompt=prompt, schema=schema))
        if not self.responses:
            raise AssertionError(
                f"FakeLLM ran out of scripted responses.\n"
                f"Unexpected call — system prompt started with: {system[:80]!r}\n"
                f"prompt started with: {prompt[:120]!r}"
            )
        return self.responses.pop(0)


@dataclass
class FakeIO:
    """Feeds scripted answers; collects everything said to the learner."""

    answers: list[str] = field(default_factory=list)
    optional_answers: list[str] = field(default_factory=list)
    said: list[str] = field(default_factory=list)

    def say(self, text: str) -> None:
        self.said.append(text)

    def ask(self, prompt: str) -> str:
        if not self.answers:
            raise AssertionError(f"FakeIO ran out of answers at prompt: {prompt!r}")
        return self.answers.pop(0)

    def ask_optional(self, prompt: str) -> str:
        if self.optional_answers:
            return self.optional_answers.pop(0)
        return ""

    def transcript(self) -> str:
        return "\n".join(self.said)
