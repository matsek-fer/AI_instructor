"""Small shared text helpers."""

from __future__ import annotations

CHOICE_LETTERS = "ABCDEFGHIJ"


def format_choices(choices: list[str]) -> str:
    """Render options as 'A. ...' lines — the same labels the learner sees,
    so an answer like "B" is unambiguous to the grader."""
    return "\n".join(
        f"{letter}. {choice}" for letter, choice in zip(CHOICE_LETTERS, choices)
    )
