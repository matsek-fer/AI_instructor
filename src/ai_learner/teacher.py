"""Teacher: one atomic reasoning step per DAG node, with mandatory assessment.

Every step is fact-checked by the verifier sub-agent before it reaches the
learner; every step ends in a targeted comprehension question; failed
assessments trigger dynamic recalibration (re-teach differently, or splice
remedial sub-nodes into the DAG).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import prompts, schemas
from .dag import ConceptDAG, ConceptNode
from .llm import LLM
from .subagents.factcheck import FactChecker
from .textformat import clamp_choices, format_choices


@dataclass
class TeachingStep:
    explanation: str
    needs_visual: bool
    visual_description: str
    question: str
    kind: str
    choices: list[str]
    #: Issues the verifier still reported on the final draft, when the retry
    #: budget was exhausted without producing a clean step. Empty == verified.
    verification_issues: list[str] = field(default_factory=list)


@dataclass
class AssessmentResult:
    passed: bool
    feedback: str
    remedial_concepts: list[dict] = field(default_factory=list)


class Teacher:
    def __init__(self, llm: LLM, fact_checker: FactChecker, factcheck_max_retries: int = 2):
        self._llm = llm
        self._fact_checker = fact_checker
        self._factcheck_max_retries = factcheck_max_retries

    def teach(
        self,
        topic: str,
        node: ConceptNode,
        dag: ConceptDAG,
        prior_attempt_feedback: str = "",
    ) -> TeachingStep:
        """Produce one teaching step for `node`.

        Every draft — including the last one — is fact-checked before being
        returned. If the retry budget runs out with issues still open, the
        final draft is returned with ``verification_issues`` set so the
        caller can surface a caution instead of presenting it as verified.
        """
        step = self._generate(topic, node, dag, prior_attempt_feedback, issues=[])
        for attempt in range(self._factcheck_max_retries + 1):
            issues = self._fact_checker.check_step(topic, node.title, step.explanation)
            if not issues:
                return step
            if attempt < self._factcheck_max_retries:
                step = self._generate(topic, node, dag, prior_attempt_feedback, issues)
            else:
                step.verification_issues = issues
        return step

    def _generate(
        self,
        topic: str,
        node: ConceptNode,
        dag: ConceptDAG,
        prior_attempt_feedback: str,
        issues: list[str],
    ) -> TeachingStep:
        completed = [
            dag.nodes[nid].title for nid in dag.completed_ids()
        ]
        prompt_parts = [
            f"Topic: {topic}",
            f"Concepts already completed: {', '.join(completed) or '(none yet)'}",
            f"Node to teach now: {node.title} — {node.description}",
        ]
        if prior_attempt_feedback:
            prompt_parts.append(
                "The learner failed the previous assessment of this node. "
                f"Grader feedback: {prior_attempt_feedback}\n"
                "Re-teach the same idea from a different angle, broken down further."
            )
        if issues:
            listing = "\n".join(f"- {issue}" for issue in issues)
            prompt_parts.append(
                f"Your previous draft was rejected by the verifier:\n{listing}\n"
                "Produce a corrected step."
            )
        result = self._llm.structured(
            system=prompts.TEACHER,
            prompt="\n".join(prompt_parts),
            schema=schemas.TEACH_STEP,
        )
        kind = result.get("kind", "short_answer")
        choices = clamp_choices(result.get("choices") or []) if kind == "multiple_choice" else []
        if kind == "multiple_choice" and len(choices) < 2:
            kind, choices = "short_answer", []
        return TeachingStep(
            explanation=result.get("explanation", ""),
            needs_visual=bool(result.get("needs_visual")),
            visual_description=result.get("visual_description", ""),
            question=result.get("question", ""),
            kind=kind,
            choices=choices,
        )

    def assess(
        self, topic: str, node: ConceptNode, step: TeachingStep, answer: str
    ) -> AssessmentResult:
        choices = format_choices(step.choices)
        result = self._llm.structured(
            system=prompts.ASSESSMENT_EVALUATION,
            prompt=(
                f"Topic: {topic}\n"
                f"Concept just taught: {node.title}\n"
                f"Teaching step shown:\n---\n{step.explanation}\n---\n"
                f"Assessment question: {step.question}\n"
                + (f"Choices:\n{choices}\n" if choices else "")
                + f"Learner's answer: {answer}"
            ),
            schema=schemas.ASSESSMENT,
        )
        return AssessmentResult(
            passed=bool(result.get("passed")),
            feedback=result.get("feedback", ""),
            remedial_concepts=list(result.get("remedial_concepts") or []),
        )
