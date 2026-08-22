"""Fact-checking / verification sub-agent.

Runs in two places (spec §3): before planning, to validate the concepts that
will make up the DAG; and before every teaching step is shown, to verify
factual claims and mathematical derivations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import prompts, schemas
from ..llm import LLM


@dataclass
class ConceptVerdict:
    concept_id: str
    accurate: bool
    issue: str = ""
    correction: str = ""


@dataclass
class FactCheckReport:
    verdicts: list[ConceptVerdict] = field(default_factory=list)
    notes: str = ""

    @property
    def corrections(self) -> list[ConceptVerdict]:
        return [v for v in self.verdicts if not v.accurate]

    def summary(self) -> str:
        if not self.corrections:
            return self.notes or "All planned concepts verified."
        flagged = ", ".join(v.concept_id for v in self.corrections)
        return f"{self.notes or 'Corrections applied.'} (flagged: {flagged})"


class FactChecker:
    def __init__(self, llm: LLM):
        self._llm = llm

    def check_concepts(self, topic: str, concepts: list[dict]) -> FactCheckReport:
        """Verify the concept list feeding the planner."""
        listing = "\n".join(
            f"- {c['id']}: {c['title']} — {c.get('description', '')}" for c in concepts
        )
        result = self._llm.structured(
            system=prompts.FACT_CHECK,
            prompt=f"Target topic: {topic}\nProposed concepts:\n{listing}",
            schema=schemas.FACT_CHECK,
        )
        return FactCheckReport(
            verdicts=[
                ConceptVerdict(
                    concept_id=v.get("concept_id", ""),
                    accurate=bool(v.get("accurate")),
                    issue=v.get("issue", ""),
                    correction=v.get("correction", ""),
                )
                for v in result.get("verdicts") or []
            ],
            notes=result.get("notes", ""),
        )

    def check_step(self, topic: str, concept_title: str, explanation: str) -> list[str]:
        """Return the list of factual/derivational issues in a teaching step."""
        result = self._llm.structured(
            system=prompts.CONTENT_CHECK,
            prompt=(
                f"Topic: {topic}\n"
                f"Concept being taught: {concept_title}\n"
                f"Teaching step to verify:\n---\n{explanation}\n---"
            ),
            schema=schemas.CONTENT_CHECK,
        )
        if result.get("sound"):
            return []
        return [issue for issue in result.get("issues") or [] if issue]
