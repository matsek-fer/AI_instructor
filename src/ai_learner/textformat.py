"""Small shared text helpers."""

from __future__ import annotations

import random

CHOICE_LETTERS = "ABCDEFGHIJ"


def clamp_choices(choices: list[str]) -> list[str]:
    """Cap options at the number of letters we can label (A-J).

    The schemas ask for 3-5 options in prose only, so an over-long list from
    the model must be clamped once, up front — otherwise display, grading,
    and the note would silently disagree about which options exist.
    """
    return list(choices)[: len(CHOICE_LETTERS)]


def prepare_choices(
    raw: list[str] | None, kind: str, rng: random.Random | None = None
) -> tuple[str, list[str]]:
    """Normalize a model-produced option list: clamp, degenerate-check, shuffle.

    The shuffle is the load-bearing part: models draft the correct answer
    first and then invent distractors, so without it the answer is almost
    always option A. Clamping happens BEFORE shuffling so the (first-listed,
    hence likely correct) option can never be clamped away.
    """
    if kind != "multiple_choice":
        return "short_answer", []
    choices = clamp_choices(raw or [])
    if len(choices) < 2:
        return "short_answer", []
    (rng or random).shuffle(choices)
    return kind, choices


def format_choices(choices: list[str]) -> str:
    """Render options as 'A. ...' lines — the same labels the learner sees,
    so an answer like "B" is unambiguous to the grader."""
    return "\n".join(
        f"{letter}. {choice}" for letter, choice in zip(CHOICE_LETTERS, choices)
    )
