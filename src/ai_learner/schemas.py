"""JSON Schemas for structured model outputs.

Every schema follows the structured-outputs constraints: all objects carry
``additionalProperties: false`` and list every property in ``required``
(optionality is expressed in prose in the field descriptions instead).
"""

from __future__ import annotations


def _obj(properties: dict, **kwargs) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
        **kwargs,
    }


_CONCEPT = _obj(
    {
        "id": {
            "type": "string",
            "description": "Short snake_case identifier, e.g. 'chain_rule'.",
        },
        "title": {"type": "string", "description": "Human-readable concept name."},
        "description": {
            "type": "string",
            "description": "One sentence on what mastering this concept means.",
        },
    }
)

#: Ordered prerequisite ladder, foundational first.
LADDER = _obj(
    {
        "concepts": {
            "type": "array",
            "items": _CONCEPT,
            "description": (
                "6-12 prerequisite concepts for the topic, strictly ordered from "
                "most foundational (index 0) to most advanced (the topic itself)."
            ),
        }
    }
)

#: One diagnostic question targeting a single concept.
QUESTION = _obj(
    {
        "question": {
            "type": "string",
            "description": "A single high-signal diagnostic question. LaTeX allowed.",
        },
        "kind": {"type": "string", "enum": ["multiple_choice", "short_answer"]},
        "choices": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 options for multiple_choice; empty for short_answer.",
        },
    }
)

#: Grading of a probe answer.
EVALUATION = _obj(
    {
        "correct": {"type": "boolean"},
        "feedback": {
            "type": "string",
            "description": "One terse sentence: why the answer is right or wrong.",
        },
    }
)

#: Fact-check verdicts over the planned concept list.
FACT_CHECK = _obj(
    {
        "verdicts": {
            "type": "array",
            "items": _obj(
                {
                    "concept_id": {"type": "string"},
                    "accurate": {"type": "boolean"},
                    "issue": {
                        "type": "string",
                        "description": "Empty when accurate; else the factual problem.",
                    },
                    "correction": {
                        "type": "string",
                        "description": "Empty when accurate; else the corrected framing.",
                    },
                }
            ),
        },
        "notes": {
            "type": "string",
            "description": "One-line overall verdict for the session log.",
        },
    }
)

#: The learning-plan DAG. Edges are given as per-node prerequisite lists.
DAG_PLAN = _obj(
    {
        "nodes": {
            "type": "array",
            "items": _obj(
                {
                    "id": {"type": "string", "description": "snake_case identifier."},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "prerequisites": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "ids of nodes that must be taught first.",
                    },
                }
            ),
            "description": (
                "Concepts from the learner's knowledge boundary up to full mastery "
                "of the topic, as a dependency graph. Must be acyclic."
            ),
        }
    }
)

#: One atomic teaching step for a single DAG node.
TEACH_STEP = _obj(
    {
        "explanation": {
            "type": "string",
            "description": (
                "Exactly ONE reasoning step in Markdown. Inline math as $...$, "
                "display math as $$...$$. No preamble, no recap of prior steps."
            ),
        },
        "needs_visual": {
            "type": "boolean",
            "description": "True only if a diagram would materially aid this step.",
        },
        "visual_description": {
            "type": "string",
            "description": "Empty unless needs_visual; else what the diagram must show.",
        },
        "question": {
            "type": "string",
            "description": "Short targeted comprehension check for this step.",
        },
        "kind": {"type": "string", "enum": ["multiple_choice", "short_answer"]},
        "choices": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 options for multiple_choice; empty for short_answer.",
        },
    }
)

#: Grading of an assessment answer, with optional remediation plan.
ASSESSMENT = _obj(
    {
        "passed": {"type": "boolean"},
        "feedback": {
            "type": "string",
            "description": "Terse, rigorous feedback on the answer. LaTeX allowed.",
        },
        "remedial_concepts": {
            "type": "array",
            "items": _CONCEPT,
            "description": (
                "Empty when passed, or when a re-explanation suffices. Otherwise "
                "1-2 smaller prerequisite concepts to splice in before this node."
            ),
        },
    }
)

#: Verification of a teaching step's factual/mathematical soundness.
CONTENT_CHECK = _obj(
    {
        "sound": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Empty when sound; else each factual or derivational error.",
        },
    }
)

#: SVG generation output.
SVG = _obj(
    {
        "svg": {
            "type": "string",
            "description": "A complete, self-contained <svg> document.",
        }
    }
)

#: SVG self-inspection output.
SVG_REVIEW = _obj(
    {
        "approved": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Layout/legibility problems found; empty when approved.",
        },
        "corrected_svg": {
            "type": "string",
            "description": "Empty when approved; else the full corrected <svg> document.",
        },
    }
)
