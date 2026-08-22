"""Probe module: locate the learner's exact knowledge boundary.

The harness — not the model — owns the search strategy. The model generates a
prerequisite ladder, one diagnostic question per probed concept, and grades
answers; a deterministic binary search over the ladder decides which concept
to probe next and when the boundary is pinpointed. This keeps the number of
questions at O(log n) and makes probing impossible to skip.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import prompts, schemas
from .dag import slugify
from .errors import StructuredOutputError
from .llm import LLM
from .session import ProbeRecord
from .textformat import clamp_choices, format_choices


@dataclass
class BoundarySearch:
    """Deterministic binary search over a ladder of ``size`` concepts.

    Invariant: every concept below ``low`` is known, every concept above
    ``high`` is unknown. The search converges when ``low > high``; ``low`` is
    then the index of the first unknown concept (== ``size`` when the learner
    knows everything probed).
    """

    size: int
    low: int = 0
    high: int = -1  # set in __post_init__

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("ladder must be non-empty")
        if self.high == -1:
            self.high = self.size - 1

    @property
    def done(self) -> bool:
        return self.low > self.high

    @property
    def boundary(self) -> int:
        if not self.done:
            raise ValueError("search has not converged")
        return self.low

    def next_index(self) -> int:
        if self.done:
            raise ValueError("search already converged")
        return (self.low + self.high) // 2

    def record(self, index: int, correct: bool) -> None:
        if correct:
            self.low = index + 1
        else:
            self.high = index - 1


class ProbeModule:
    def __init__(self, llm: LLM):
        self._llm = llm

    def generate_ladder(self, topic: str, background: str) -> list[dict]:
        """Ordered prerequisite concepts, foundational first."""
        result = self._llm.structured(
            system=prompts.LADDER,
            prompt=(
                f"Topic to master: {topic}\n"
                f"Learner's stated background: {background or 'none given'}"
            ),
            schema=schemas.LADDER,
        )
        concepts = result.get("concepts") or []
        if not concepts:
            raise StructuredOutputError("Model returned an empty prerequisite ladder.")
        seen: set[str] = set()
        cleaned: list[dict] = []
        for concept in concepts:
            concept_id = slugify(concept.get("id") or concept.get("title", ""))
            base, suffix = concept_id, 2
            while concept_id in seen:
                concept_id = f"{base}_{suffix}"
                suffix += 1
            seen.add(concept_id)
            cleaned.append(
                {
                    "id": concept_id,
                    "title": concept.get("title", concept_id),
                    "description": concept.get("description", ""),
                }
            )
        return cleaned

    def ask_question(
        self, topic: str, background: str, concept: dict, asked_before: list[ProbeRecord]
    ) -> ProbeRecord:
        """Generate one diagnostic question for a single ladder concept."""
        history = "\n".join(
            f"- {record.concept_title}: {record.question} "
            f"({'correct' if record.correct else 'incorrect'})"
            for record in asked_before
        )
        result = self._llm.structured(
            system=prompts.PROBE_QUESTION,
            prompt=(
                f"Topic: {topic}\n"
                f"Learner background: {background or 'none given'}\n"
                f"Target concept: {concept['title']} — {concept.get('description', '')}\n"
                f"Questions already asked (do not repeat):\n{history or '(none)'}"
            ),
            schema=schemas.QUESTION,
        )
        kind = result.get("kind", "short_answer")
        choices = clamp_choices(result.get("choices") or []) if kind == "multiple_choice" else []
        if kind == "multiple_choice" and len(choices) < 2:
            kind, choices = "short_answer", []
        return ProbeRecord(
            concept_id=concept["id"],
            concept_title=concept["title"],
            question=result.get("question", ""),
            kind=kind,
            choices=choices,
        )

    def evaluate(self, topic: str, record: ProbeRecord, answer: str) -> None:
        """Grade the learner's answer in place on the record."""
        choices = format_choices(record.choices)
        result = self._llm.structured(
            system=prompts.PROBE_EVALUATION,
            prompt=(
                f"Topic: {topic}\n"
                f"Concept probed: {record.concept_title}\n"
                f"Question: {record.question}\n"
                + (f"Choices:\n{choices}\n" if choices else "")
                + f"Learner's answer: {answer}"
            ),
            schema=schemas.EVALUATION,
        )
        record.user_answer = answer
        record.correct = bool(result.get("correct"))
        record.feedback = result.get("feedback", "")
