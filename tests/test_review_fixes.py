"""Regression tests for the defects found in the adversarial review pass."""

from ai_learner import markdown_log
from ai_learner.config import Config
from ai_learner.dag import STATUS_COMPLETED, ConceptDAG, ConceptNode
from ai_learner.engine import TutorEngine
from ai_learner.planner import Planner
from ai_learner.probe import ProbeModule
from ai_learner.session import (
    PHASE_DONE,
    PHASE_TEACH,
    LessonRecord,
    SessionState,
    SessionStore,
)
from ai_learner.subagents.factcheck import FactChecker, FactCheckReport
from ai_learner.subagents.svg_agent import SVGAgent, inspect_svg
from ai_learner.teacher import Teacher

from conftest import FakeIO, FakeLLM

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect x="10" y="10" width="50" height="30" fill="#ccc"/>'
    "</svg>"
)


# -- review marker for abandoned nodes ------------------------------------

def test_needs_review_survives_serialization_and_styles_mermaid():
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="hard", title="Hard", status=STATUS_COMPLETED,
                             needs_review=True))
    dag.add_node(ConceptNode(id="easy", title="Easy", status=STATUS_COMPLETED))
    restored = ConceptDAG.from_dict(dag.to_dict())
    assert restored.nodes["hard"].needs_review
    assert restored.review_ids() == ["hard"]
    mermaid = restored.to_mermaid()
    assert "(review)" in mermaid
    assert "class hard review;" in mermaid
    assert "class easy completed;" in mermaid
    # A flagged node must NOT also carry the mastered style.
    assert "class hard completed" not in mermaid
    assert "hard,easy completed" not in mermaid


def test_completion_section_never_claims_mastery_of_review_nodes():
    state = SessionState(name="s", phase=PHASE_DONE, topic="t")
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="hard", title="Hard thing", status=STATUS_COMPLETED,
                             needs_review=True))
    state.dag = dag
    text = markdown_log.render(state)
    assert "are mastered" not in text
    assert "marked for review" in text
    assert "Hard thing" in text
    assert "(1 marked for review)" in text


def make_teach_state(store: SessionStore) -> SessionState:
    state = store.create("teach")
    state.topic = "topic"
    state.background = "bg"
    state.phase = PHASE_TEACH
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="hard", title="Hard"))
    state.dag = dag
    return state


STEP = {
    "explanation": "One step.",
    "needs_visual": False,
    "visual_description": "",
    "question": "Check?",
    "kind": "short_answer",
    "choices": [],
}
SOUND = {"sound": True, "issues": []}
FAIL = {"passed": False, "feedback": "No.", "remedial_concepts": []}


def test_give_up_path_flags_node_for_review(tmp_path):
    config = Config(vault=tmp_path, enable_fallbacks=False)
    store = SessionStore(config.vault)
    state = make_teach_state(store)
    llm = FakeLLM([STEP, SOUND, FAIL] * 3)  # three failed attempts
    io = FakeIO(answers=["a1", "a2", "a3"], optional_answers=[""])  # Enter = default N
    TutorEngine(config, store, state, llm, io)._run_teach()
    assert state.phase == PHASE_DONE
    node = state.dag.nodes["hard"]
    assert node.status == STATUS_COMPLETED
    assert node.needs_review
    log = store.log_path("teach").read_text(encoding="utf-8")
    assert "marked for review" in log
    assert "All concepts in the learning plan are mastered" not in log


# -- teacher: final draft is always verified -------------------------------

def test_exhausted_factcheck_retries_surface_issues_not_silence():
    llm = FakeLLM([
        STEP, {"sound": False, "issues": ["err1"]},
        STEP, {"sound": False, "issues": ["err2"]},
        STEP, {"sound": False, "issues": ["err3"]},
    ])
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="n", title="N"))
    teacher = Teacher(llm, FactChecker(llm), factcheck_max_retries=2)
    step = teacher.teach("t", dag.nodes["n"], dag)
    # Three generations, three checks — the returned draft was checked.
    assert len(llm.calls) == 6
    assert step.verification_issues == ["err3"]


def test_lesson_caution_is_rendered():
    state = SessionState(name="s", phase=PHASE_TEACH, topic="t")
    state.lessons = [
        LessonRecord(node_id="n", title="N", explanation="E",
                     caution="Automated verification flagged unresolved issues: x")
    ]
    assert "⚠️ **Caution:**" in markdown_log.render(state)


# -- svg agent: never embed a review-rejected drawing ----------------------

def test_rejected_svg_without_correction_is_dropped():
    llm = FakeLLM([
        {"svg": GOOD_SVG},
        {"approved": False, "issues": ["overlapping text"], "corrected_svg": ""},
    ])
    assert SVGAgent(llm).create("t", "c", "d") is None


def test_never_approved_svg_is_dropped():
    other = GOOD_SVG.replace("#ccc", "#ddd")
    llm = FakeLLM([
        {"svg": GOOD_SVG},
        {"approved": False, "issues": ["bad"], "corrected_svg": other},
        {"approved": False, "issues": ["still bad"], "corrected_svg": GOOD_SVG},
        {"approved": False, "issues": ["worse"], "corrected_svg": other},
    ])
    assert SVGAgent(llm, max_revisions=3).create("t", "c", "d") is None


# -- svg inspector: coordinate-system scoping ------------------------------

def test_gradient_and_defs_coordinates_are_not_bounds_checked():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        "<defs>"
        '<linearGradient id="g" x1="0" y1="0" x2="1" y2="0"/>'
        "</defs>"
        '<rect x="10" y="10" width="50" height="30" fill="url(#g)"/>'
        "</svg>"
    )
    result = inspect_svg(svg)
    assert result.ok, result.issues


def test_nested_svg_children_use_their_own_viewbox():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<svg viewBox="0 0 1000 1000" x="0" y="0" width="10" height="10">'
        '<circle cx="900" cy="900" r="5"/>'
        "</svg>"
        "</svg>"
    )
    result = inspect_svg(svg)
    assert result.ok, result.issues


def test_transformed_elements_are_left_to_the_reviewer():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<g transform="translate(5, 5)"><rect x="200" y="200" width="1" height="1"/></g>'
        '<rect x="10" y="10" width="5" height="5"/>'
        "</svg>"
    )
    result = inspect_svg(svg)
    assert result.ok, result.issues


def test_safety_checks_still_apply_inside_exempt_containers():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<defs><script>evil()</script></defs>"
        '<rect x="1" y="1" width="2" height="2"/>'
        "</svg>"
    )
    result = inspect_svg(svg)
    assert any("script" in issue for issue in result.issues)


# -- planner: duplicate ids don't mis-wire edges ---------------------------

def test_duplicate_plan_ids_keep_edges_on_the_right_nodes():
    llm = FakeLLM([
        {
            "nodes": [
                {"id": "limits", "title": "Limits of functions", "description": "",
                 "prerequisites": []},
                {"id": "limits", "title": "Limits of sequences", "description": "",
                 "prerequisites": []},
                {"id": "derivatives", "title": "Derivatives", "description": "",
                 "prerequisites": ["limits"]},
            ]
        }
    ])
    dag = Planner(llm).build_dag("t", [], [], FactCheckReport())
    assert set(dag.nodes) == {"limits", "limits_2", "derivatives"}
    # The reference resolves to the FIRST occurrence, not the last duplicate.
    assert dag.prerequisites("derivatives") == {"limits"}
    assert dag.prerequisites("limits_2") == set()


# -- session names: normalization and traversal safety ---------------------

def test_resume_accepts_the_name_typed_at_start(tmp_path):
    store = SessionStore(tmp_path)
    store.create("My Calculus")
    loaded = store.load("My Calculus")  # raw name, as the user typed it
    assert loaded.name == "my-calculus"


def test_hostile_session_name_cannot_escape_vault(tmp_path):
    vault = tmp_path / "vault"
    store = SessionStore(vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    resolved = store.session_dir("../outside/evil")
    assert vault.resolve() in resolved.resolve().parents


def test_latest_skips_corrupt_sessions(tmp_path):
    store = SessionStore(tmp_path)
    store.create("good")
    bad = store.create("bad")
    (store.session_dir(bad.name) / "state.json").write_text("{broken", encoding="utf-8")
    assert store.latest() == "good"


def test_dangling_dag_edge_is_corruption_not_a_crash(tmp_path):
    """A state.json written by another tool with an edge to a missing node
    must surface as SessionError (and be skipped by latest()), not DAGError."""
    import json
    import pytest
    from ai_learner.errors import SessionError

    store = SessionStore(tmp_path)
    state = store.create("edgy")
    path = store.session_dir(state.name) / "state.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dag"] = {
        "nodes": [{"id": "a", "title": "A", "description": "",
                   "status": "pending", "remedial": False, "needs_review": False}],
        "edges": [["a", "ghost"]],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SessionError, match="corrupt"):
        store.load("edgy")
    store.create("healthy")
    assert store.latest() == "healthy"


# -- engine: dangling lessons pruned on resume -----------------------------

def test_dangling_unanswered_lesson_is_pruned_on_teach_resume(tmp_path):
    config = Config(vault=tmp_path, enable_fallbacks=False)
    store = SessionStore(config.vault)
    state = make_teach_state(store)
    state.dag.nodes["hard"].status = STATUS_COMPLETED  # nothing left to teach
    state.lessons = [
        LessonRecord(node_id="hard", title="Hard", explanation="E1",
                     user_answer="ans", passed=True),
        LessonRecord(node_id="hard", title="Hard", explanation="E2"),  # dangling
    ]
    TutorEngine(config, store, state, FakeLLM(), FakeIO())._run_teach()
    assert [lesson.explanation for lesson in state.lessons] == ["E1"]
    assert state.phase == PHASE_DONE


# -- choices are clamped to the labelable range ----------------------------

def test_probe_choices_clamped_to_ten():
    many = [str(i) for i in range(15)]
    llm = FakeLLM([{"question": "Q", "kind": "multiple_choice", "choices": many}])
    record = ProbeModule(llm).ask_question("t", "", {"id": "c", "title": "C"}, [])
    assert len(record.choices) == 10
