"""Runtime configuration for the AI-Learner harness."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_VAULT = "sessions"


@dataclass
class Config:
    #: Claude model id used for every call (tutor and sub-agents alike).
    model: str = field(default_factory=lambda: os.environ.get("AI_LEARNER_MODEL", DEFAULT_MODEL))
    #: Reasoning effort: low | medium | high | xhigh | max.
    effort: str = field(default_factory=lambda: os.environ.get("AI_LEARNER_EFFORT", DEFAULT_EFFORT))
    #: Directory holding session folders (each with state.json + session.md).
    #: Point this at an Obsidian vault folder for live rendering.
    vault: Path = field(
        default_factory=lambda: Path(os.environ.get("AI_LEARNER_VAULT", DEFAULT_VAULT))
    )
    #: Server-side refusal fallbacks (beta). On a safety-classifier decline the
    #: API transparently re-serves the request on Anthropic's recommended
    #: fallback model instead of failing the session.
    enable_fallbacks: bool = True
    #: Output ceiling for a single model call.
    max_tokens: int = 16000
    #: How many times the SVG sub-agent may revise its own drawing.
    svg_max_revisions: int = 3
    #: How many times a factually-flagged teaching step is regenerated.
    factcheck_max_retries: int = 2
    #: Cap on remedial nodes spliced in for a single struggling concept.
    max_remedials_per_node: int = 2
    #: Cap on probe questions (safety net on top of binary search).
    max_probe_questions: int = 12
