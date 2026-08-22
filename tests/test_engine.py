"""End-to-end engine test: a full session against a fully scripted model.

The script walks setup -> probe (binary search over 4 concepts) -> fact-check
-> plan -> teach (including one SVG illustration, one failed assessment with a
remedial detour) -> done, and then checks the persisted state and the rendered
Markdown log.
"""

from ai_learner.config import Config
from ai_learner.engine import TutorEngine
from ai_learner.session import PHASE_DONE, SessionStore

from conftest import FakeIO, FakeLLM

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect x="10" y="10" width="50" height="30" fill="#ccc"/>'
    '<text x="20" y="60" font-size="12">v</text>'
    "</svg>"
)

LADDER = {
    "concepts": [
        {"id": "c0", "title": "C0", "description": "foundation"},
        {"id": "c1", "title": "C1", "description": "next"},
        {"id": "c2", "title": "C2", "description": "harder"},
        {"id": "c3", "title": "C3", "description": "mastery"},
    ]
}

def question(text):
    return {"question": text, "kind": "short_answer", "choices": []}

def step(explanation, needs_visual=False, visual=""):
    return {
        "explanation": explanation,
        "needs_visual": needs_visual,
        "visual_description": visual,
        "question": f"Check on: {explanation[:20]}",
        "kind": "short_answer",
        "choices": [],
    }

SOUND = {"sound": True, "issues": []}
PASS = {"passed": True, "feedback": "Correct.", "remedial_concepts": []}


def build_script() -> FakeLLM:
    return FakeLLM([
        # -- probe: ladder, then binary search over 4 concepts.
        LADDER,
        # search: low=0 high=3 -> mid 1 (C1): correct -> low=2
        question("Q about C1"),
        {"correct": True, "feedback": "Yes."},
        # search: low=2 high=3 -> mid 2 (C2): incorrect -> high=1; done, boundary=2
        question("Q about C2"),
        {"correct": False, "feedback": "No."},
        # -- plan: fact check over [c2, c3], then the DAG.
        {
            "verdicts": [
                {"concept_id": "c2", "accurate": True, "issue": "", "correction": ""},
                {"concept_id": "c3", "accurate": True, "issue": "", "correction": ""},
            ],
            "notes": "Verified.",
        },
        {
            "nodes": [
                {"id": "n1", "title": "N1", "description": "", "prerequisites": []},
                {"id": "n2", "title": "N2", "description": "", "prerequisites": ["n1"]},
            ]
        },
        # -- teach n1 (no visual): step, verify, assess pass.
        step("N1 explanation with $x$"),
        SOUND,
        PASS,
        # -- teach n2 (visual): step, verify, svg generate, svg self-review,
        #    assess FAIL with one remedial concept.
        step("N2 explanation", needs_visual=True, visual="a diagram of N2"),
        SOUND,
        {"svg": GOOD_SVG},
        {"approved": True, "issues": [], "corrected_svg": ""},
        {
            "passed": False,
            "feedback": "Missed the key idea.",
            "remedial_concepts": [
                {"id": "r1", "title": "R1", "description": "smaller piece"}
            ],
        },
        # -- teach remedial r1: step, verify, assess pass.
        step("R1 remedial explanation"),
        SOUND,
        PASS,
        # -- re-teach n2: step, verify, svg again, assess pass.
        step("N2 second angle", needs_visual=True, visual="a diagram of N2"),
        SOUND,
        {"svg": GOOD_SVG},
        {"approved": True, "issues": [], "corrected_svg": ""},
        PASS,
    ])


def run_session(tmp_path):
    config = Config(vault=tmp_path / "vault", enable_fallbacks=False)
    store = SessionStore(config.vault)
    state = store.create("e2e")
    llm = build_script()
    io = FakeIO(
        answers=[
            "Calculus",       # topic
            "probe answer 1",
            "probe answer 2",
            "n1 answer",
            "n2 answer (wrong)",
            "r1 answer",
            "n2 answer (right)",
        ],
        optional_answers=["I know some algebra"],
    )
    engine = TutorEngine(config, store, state, llm, io)
    engine.run()
    return store, state, llm, io


def test_full_session(tmp_path):
    store, state, llm, io = run_session(tmp_path)

    # Phases and boundary.
    assert state.phase == PHASE_DONE
    assert state.topic == "Calculus"
    assert state.background == "I know some algebra"
    assert state.boundary_index == 2
    assert len(state.probe_records) == 2

    # DAG: remedial spliced in before n2, everything completed.
    assert state.dag.topological_order() == ["n1", "r1", "n2"]
    assert state.dag.nodes["r1"].remedial
    assert state.dag.is_complete()

    # Lessons: n1, n2 (failed), r1, n2 (passed).
    outcomes = [(lesson.node_id, lesson.passed) for lesson in state.lessons]
    assert outcomes == [("n1", True), ("n2", False), ("r1", True), ("n2", True)]

    # The SVG asset exists on disk and is referenced from the lesson.
    svg_lessons = [lesson for lesson in state.lessons if lesson.svg_path]
    assert svg_lessons
    for lesson in svg_lessons:
        asset = store.session_dir("e2e") / lesson.svg_path
        assert asset.exists()
        assert asset.read_text(encoding="utf-8").startswith("<svg")

    # All model calls consumed exactly.
    assert llm.responses == []

    # Opening question was asked verbatim (spec §6).
    assert any(
        "What topic would you like to master today" in text for text in io.said
    )


def test_full_session_writes_live_markdown(tmp_path):
    store, state, _, _ = run_session(tmp_path)
    log = store.log_path("e2e").read_text(encoding="utf-8")
    assert "# Learning Session: Calculus" in log
    assert "## Knowledge Probe" in log
    assert "```mermaid" in log
    assert "n1 --> r1" in log or "r1 --> n2" in log
    assert "## Lessons" in log
    assert "![" in log  # embedded SVG
    assert "## Session Complete" in log


def test_resume_replays_probe_state(tmp_path):
    """Interrupt after the first probe answer; a fresh engine must continue the
    binary search from the same point instead of restarting it."""
    config = Config(vault=tmp_path / "vault", enable_fallbacks=False)
    store = SessionStore(config.vault)
    state = store.create("resume")

    llm = FakeLLM([
        LADDER,
        question("Q about C1"),
        {"correct": True, "feedback": "Yes."},
    ])
    io = FakeIO(answers=["Calculus", "probe answer 1"], optional_answers=[""])
    engine = TutorEngine(config, store, state, llm, io)
    # Run setup, then probe until the scripted answers run out.
    engine._run_setup()
    try:
        engine._run_probe()
    except AssertionError:
        pass  # FakeIO exhausted mid-probe == user hit Ctrl-C

    # Reload from disk, as `ai-learner resume` would.
    resumed = store.load("resume")
    assert len(resumed.probe_records) == 1

    llm2 = FakeLLM([
        question("Q about C2"),
        {"correct": False, "feedback": "No."},
    ])
    io2 = FakeIO(answers=["probe answer 2"])
    engine2 = TutorEngine(config, store, resumed, llm2, io2)
    engine2._run_probe()
    # Search continued: only one more question, boundary at 2.
    assert resumed.boundary_index == 2
    assert len(resumed.probe_records) == 2
