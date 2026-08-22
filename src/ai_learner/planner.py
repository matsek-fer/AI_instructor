"""Planner: turn the knowledge boundary into a validated learning-path DAG.

The model proposes nodes with prerequisite lists; the harness assembles them
into a ``ConceptDAG``, which structurally enforces acyclicity and edge
validity. A plan that fails validation is sent back to the model with the
exact error, once — the constraint is enforced by code, not by prompting.
"""

from __future__ import annotations

from . import prompts, schemas
from .dag import ConceptDAG, ConceptNode, slugify
from .errors import DAGError, StructuredOutputError
from .llm import LLM
from .subagents.factcheck import FactCheckReport


class Planner:
    def __init__(self, llm: LLM, max_retries: int = 2):
        self._llm = llm
        self._max_retries = max_retries

    def build_dag(
        self,
        topic: str,
        known_concepts: list[dict],
        to_learn: list[dict],
        report: FactCheckReport,
    ) -> ConceptDAG:
        prompt = self._prompt(topic, known_concepts, to_learn, report)
        last_error: Exception | None = None
        for _ in range(1 + self._max_retries):
            result = self._llm.structured(
                system=prompts.PLANNER,
                prompt=prompt,
                schema=schemas.DAG_PLAN,
            )
            try:
                return self._assemble(result)
            except (DAGError, StructuredOutputError) as exc:
                last_error = exc
                prompt = (
                    f"{prompt}\n\nYour previous plan was structurally invalid: "
                    f"{exc}. Produce a corrected plan."
                )
        raise DAGError(f"planner failed to produce a valid DAG: {last_error}")

    def _prompt(
        self,
        topic: str,
        known_concepts: list[dict],
        to_learn: list[dict],
        report: FactCheckReport,
    ) -> str:
        known = "\n".join(f"- {c['title']}" for c in known_concepts) or "(none)"
        target = "\n".join(
            f"- {c['id']}: {c['title']} — {c.get('description', '')}" for c in to_learn
        )
        corrections = "\n".join(
            f"- {v.concept_id}: {v.issue} -> {v.correction}" for v in report.corrections
        ) or "(none)"
        return (
            f"Topic to master: {topic}\n"
            f"Concepts the learner already knows (build on these; do NOT re-teach):\n{known}\n"
            f"Concepts still to be learned (cover all of these; refine or split as needed):\n{target}\n"
            f"Verifier corrections to incorporate:\n{corrections}"
        )

    def _assemble(self, result: dict) -> ConceptDAG:
        raw_nodes = result.get("nodes") or []
        if not raw_nodes:
            raise StructuredOutputError("planner returned an empty DAG")
        dag = ConceptDAG()
        # assigned[i] is the final id of raw_nodes[i], so a node's own edges
        # always attach to itself even when the model repeats an id. For
        # *references* to a duplicated id, the first occurrence wins.
        assigned: list[str] = []
        id_map: dict[str, str] = {}
        for raw in raw_nodes:
            original = raw.get("id") or raw.get("title", "")
            node_id = slugify(original)
            base, suffix = node_id, 2
            while node_id in dag.nodes:
                node_id = f"{base}_{suffix}"
                suffix += 1
            assigned.append(node_id)
            id_map.setdefault(original, node_id)
            id_map.setdefault(slugify(original), node_id)
            dag.add_node(
                ConceptNode(
                    id=node_id,
                    title=raw.get("title", node_id),
                    description=raw.get("description", ""),
                )
            )
        for raw, node_id in zip(raw_nodes, assigned):
            for prereq in raw.get("prerequisites") or []:
                prereq_id = id_map.get(prereq) or id_map.get(slugify(prereq)) or slugify(prereq)
                if prereq_id == node_id:
                    continue  # ignore harmless self-references
                dag.add_edge(prereq_id, node_id)  # raises DAGError on cycle/unknown
        return dag
