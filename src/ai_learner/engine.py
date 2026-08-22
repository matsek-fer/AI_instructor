"""Main agent engine: session state machine controlling Probe -> Plan -> Teach.

The engine owns all control flow — which phase runs, which question is asked
next, when the plan is accepted, when a node counts as mastered. The model
supplies content (questions, plans, explanations, grades); it never decides
the flow. After every state change the session is persisted and the Markdown
log re-rendered, so the note stays live and any run is resumable.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from . import markdown_log
from .config import Config
from .dag import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_PENDING,
    ConceptNode,
    slugify,
)
from .llm import LLM
from .probe import BoundarySearch, ProbeModule
from .planner import Planner
from .session import (
    PHASE_DONE,
    PHASE_PLAN,
    PHASE_PROBE,
    PHASE_SETUP,
    PHASE_TEACH,
    LessonRecord,
    SessionState,
    SessionStore,
)
from .subagents import FactChecker, SVGAgent
from .teacher import Teacher
from .textformat import CHOICE_LETTERS

OPENING_QUESTION = (
    "What topic would you like to master today, "
    "and what is your general background in related fields?"
)

#: After this many failed attempts at one node the learner chooses whether to
#: keep drilling it or move on — the safety valve against an endless loop.
MAX_ATTEMPTS_PER_NODE = 3


class IO(Protocol):
    """Interaction surface; console in production, scripted in tests."""

    def say(self, text: str) -> None: ...
    def ask(self, prompt: str) -> str: ...
    def ask_optional(self, prompt: str) -> str: ...


class ConsoleIO:
    def say(self, text: str) -> None:
        print(text)
        print()

    def ask(self, prompt: str) -> str:
        while True:
            answer = input(f"{prompt} ").strip()
            if answer:
                return answer
            print("(please enter an answer)")

    def ask_optional(self, prompt: str) -> str:
        return input(f"{prompt} ").strip()


class TutorEngine:
    def __init__(
        self,
        config: Config,
        store: SessionStore,
        state: SessionState,
        llm: LLM,
        io: IO,
    ):
        self.config = config
        self.store = store
        self.state = state
        self.io = io
        self.probe = ProbeModule(llm)
        self.fact_checker = FactChecker(llm)
        self.planner = Planner(llm)
        self.teacher = Teacher(llm, self.fact_checker, config.factcheck_max_retries)
        self.svg_agent = SVGAgent(llm, config.svg_max_revisions)
        # In-memory recalibration bookkeeping (reset on resume, deliberately).
        self._attempts: dict[str, int] = defaultdict(int)
        self._remedials: dict[str, int] = defaultdict(int)
        self._reteach_feedback: dict[str, str] = {}

    # -- lifecycle --------------------------------------------------------

    def run(self) -> None:
        handlers = {
            PHASE_SETUP: self._run_setup,
            PHASE_PROBE: self._run_probe,
            PHASE_PLAN: self._run_plan,
            PHASE_TEACH: self._run_teach,
        }
        while self.state.phase != PHASE_DONE:
            handlers[self.state.phase]()
        flagged = self.state.dag.review_ids() if self.state.dag else []
        if flagged:
            titles = ", ".join(f"*{self.state.dag.nodes[nid].title}*" for nid in flagged)
            summary = (
                f"Session complete for *{self.state.topic}* — "
                f"{len(flagged)} concept(s) marked for review: {titles}."
            )
        else:
            summary = (
                f"Session complete: every concept in the plan for "
                f"*{self.state.topic}* is mastered."
            )
        self.io.say(f"{summary}\nNotes: {self.store.log_path(self.state.name)}")

    def _sync(self) -> None:
        self.store.save(self.state)
        markdown_log.write(self.store, self.state)

    # -- phase 0: setup ---------------------------------------------------

    def _run_setup(self) -> None:
        state = self.state
        if not state.topic:
            self.io.say(OPENING_QUESTION)
            state.topic = self.io.ask(">")
        if not state.background:
            state.background = self.io.ask_optional(
                "Anything to add about your background? (Enter to continue)"
            )
        state.phase = PHASE_PROBE
        self._sync()

    # -- phase 1: probe ---------------------------------------------------

    def _run_probe(self) -> None:
        state = self.state
        if not state.ladder:
            self.io.say("Mapping the prerequisite ladder for this topic...")
            state.ladder = self.probe.generate_ladder(state.topic, state.background)
            self._sync()

        index_of = {c["id"]: i for i, c in enumerate(state.ladder)}
        search = BoundarySearch(len(state.ladder))
        # Replay already-graded questions (resume support): the search is
        # deterministic, so re-recording past results restores its exact state.
        for record in state.probe_records:
            if record.correct is not None and record.concept_id in index_of:
                search.record(index_of[record.concept_id], record.correct)

        while not search.done and len(state.probe_records) < self.config.max_probe_questions:
            index = search.next_index()
            concept = state.ladder[index]
            record = self.probe.ask_question(
                state.topic, state.background, concept, state.probe_records
            )
            self.io.say(f"**Probe — {record.concept_title}**\n\n{self._render_question(record.question, record.choices)}")
            answer = self.io.ask(">")
            self.probe.evaluate(state.topic, record, answer)
            state.probe_records.append(record)
            search.record(index, bool(record.correct))
            self.io.say(record.feedback)
            self._sync()

        state.boundary_index = search.boundary if search.done else search.low
        self._sync()
        self.io.say(self._boundary_summary())
        state.phase = PHASE_PLAN
        self._sync()

    def _boundary_summary(self) -> str:
        state = self.state
        idx = state.boundary_index or 0
        if idx >= len(state.ladder):
            return (
                "You already know every probed prerequisite — the plan will "
                "push into advanced territory."
            )
        first_unknown = state.ladder[idx]["title"]
        if idx == 0:
            return f"Boundary located: we start from the foundations, at *{first_unknown}*."
        last_known = state.ladder[idx - 1]["title"]
        return (
            f"Boundary located: you are solid up to *{last_known}*; "
            f"learning starts at *{first_unknown}*."
        )

    # -- phase 2: plan ----------------------------------------------------

    def _run_plan(self) -> None:
        state = self.state
        boundary = state.boundary_index or 0
        known = state.ladder[:boundary]
        to_learn = state.ladder[boundary:]
        if not to_learn:
            # Learner cleared the whole ladder: plan a deepening path instead.
            to_learn = [
                {
                    "id": f"advanced_{slugify(state.topic)}",
                    "title": f"Advanced {state.topic}",
                    "description": (
                        "Material beyond the probed ladder, deepening mastery "
                        "of the topic."
                    ),
                }
            ]

        self.io.say("Verifying planned concepts (fact-check sub-agent)...")
        report = self.fact_checker.check_concepts(state.topic, to_learn)
        state.fact_check_notes = report.summary()
        self._sync()

        self.io.say("Building the learning-plan DAG...")
        state.dag = self.planner.build_dag(state.topic, known, to_learn, report)
        state.phase = PHASE_TEACH
        self._sync()

        order = [state.dag.nodes[nid].title for nid in state.dag.topological_order()]
        listing = "\n".join(f"{i}. {title}" for i, title in enumerate(order, 1))
        self.io.say(
            f"Learning plan ({len(order)} concepts):\n{listing}\n\n"
            f"The full dependency graph is rendered in "
            f"{self.store.log_path(self.state.name)}"
        )

    # -- phase 3: teach ---------------------------------------------------

    def _run_teach(self) -> None:
        state = self.state
        # Drop lessons interrupted before the learner answered (Ctrl-C at the
        # check question): the node is still pending and will be re-taught, so
        # the dangling record would otherwise duplicate in the note forever.
        state.lessons = [
            lesson for lesson in state.lessons
            if lesson.user_answer or lesson.passed is not None
        ]
        while (node := state.dag.next_pending()) is not None:
            node.status = STATUS_ACTIVE
            self._sync()
            self._teach_node(node)
        state.phase = PHASE_DONE
        self._sync()

    def _teach_node(self, node: ConceptNode) -> None:
        state = self.state
        step = self.teacher.teach(
            state.topic, node, state.dag,
            prior_attempt_feedback=self._reteach_feedback.get(node.id, ""),
        )

        svg_path = ""
        if step.needs_visual and step.visual_description:
            self.io.say("(illustrating this step...)")
            svg = self.svg_agent.create(state.topic, node.title, step.visual_description)
            if svg is not None:
                svg_path = state.next_asset_name(node.id)
                self.store.write_asset(state, svg_path, svg)

        caution = ""
        if step.verification_issues:
            caution = (
                "Automated verification flagged unresolved issues in this step: "
                + "; ".join(step.verification_issues)
            )
        lesson = LessonRecord(
            node_id=node.id,
            title=node.title,
            explanation=step.explanation,
            svg_path=svg_path,
            question=step.question,
            kind=step.kind,
            choices=step.choices,
            caution=caution,
        )
        state.lessons.append(lesson)
        self._sync()

        body = f"## {node.title}\n\n{step.explanation}"
        if svg_path:
            body += f"\n\n[diagram: {svg_path}]"
        if caution:
            body += f"\n\n> Caution: {caution}"
        self.io.say(body)
        self.io.say(f"**Check:** {self._render_question(step.question, step.choices)}")
        answer = self.io.ask(">")

        result = self.teacher.assess(state.topic, node, step, answer)
        lesson.user_answer = answer
        lesson.passed = result.passed
        lesson.feedback = result.feedback
        self.io.say(result.feedback)

        if result.passed:
            node.status = STATUS_COMPLETED
            self._reteach_feedback.pop(node.id, None)
        else:
            self._recalibrate(node, result)
        self._sync()

    def _recalibrate(self, node: ConceptNode, result) -> None:
        """Dynamic recalibration after a failed assessment (spec §3)."""
        state = self.state
        self._attempts[node.id] += 1

        if self._attempts[node.id] >= MAX_ATTEMPTS_PER_NODE:
            choice = self.io.ask_optional(
                f"Still working on *{node.title}* after "
                f"{self._attempts[node.id]} attempts. Keep at it? [y/N]"
            )
            if not choice.lower().startswith("y"):
                self.io.say(
                    f"Moving on. *{node.title}* is marked for review in the notes."
                )
                # Completed for traversal (next_pending must advance), but
                # flagged so the plan and the note never claim mastery of it.
                node.status = STATUS_COMPLETED
                node.needs_review = True
                self._reteach_feedback.pop(node.id, None)
                return

        remedials = result.remedial_concepts
        if remedials and self._remedials[node.id] < self.config.max_remedials_per_node:
            budget = self.config.max_remedials_per_node - self._remedials[node.id]
            added: list[str] = []
            for concept in remedials[:budget]:
                remedial_id = slugify(concept.get("id") or concept.get("title", "remedial"))
                base, suffix = remedial_id, 2
                while remedial_id in state.dag.nodes:
                    remedial_id = f"{base}_{suffix}"
                    suffix += 1
                state.dag.insert_remedial(
                    node.id,
                    ConceptNode(
                        id=remedial_id,
                        title=concept.get("title", remedial_id),
                        description=concept.get("description", ""),
                    ),
                )
                self._remedials[node.id] += 1
                added.append(concept.get("title", remedial_id))
            node.status = STATUS_PENDING  # revisited after the remedial detour
            self.io.say(
                "Recalibrating: first we take a smaller step — "
                + ", ".join(f"*{title}*" for title in added)
                + "."
            )
        else:
            # Same node, different angle: stays active, re-taught next loop.
            self._reteach_feedback[node.id] = result.feedback
            self.io.say("Let's take the same idea from a different angle.")

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _render_question(question: str, choices: list[str]) -> str:
        if not choices:
            return question
        options = "\n".join(
            f"  {letter}. {choice}" for letter, choice in zip(CHOICE_LETTERS, choices)
        )
        return f"{question}\n{options}"
