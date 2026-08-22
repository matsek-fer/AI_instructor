"""Small shared text helpers."""

from __future__ import annotations

CHOICE_LETTERS = "ABCDEFGHIJ"


def clamp_choices(choices: list[str]) -> list[str]:
    """Cap options at the number of letters we can label (A-J).

    The schemas ask for 3-5 options in prose only, so an over-long list from
    the model must be clamped once, up front — otherwise display, grading,
    and the note would silently disagree about which options exist.
    """
    return list(choices)[: len(CHOICE_LETTERS)]


def format_choices(choices: list[str]) -> str:
    """Render options as 'A. ...' lines — the same labels the learner sees,
    so an answer like "B" is unambiguous to the grader."""
    return "\n".join(
        f"{letter}. {choice}" for letter, choice in zip(CHOICE_LETTERS, choices)
    )
