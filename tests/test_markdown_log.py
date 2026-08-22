from ai_learner import markdown_log
from ai_learner.dag import STATUS_COMPLETED, ConceptDAG, ConceptNode
from ai_learner.session import (
    PHASE_DONE,
    PHASE_PROBE,
    PHASE_TEACH,
    LessonRecord,
    ProbeRecord,
    SessionState,
    SessionStore,
)


def build_state() -> SessionState:
    state = SessionState(name="s", phase=PHASE_TEACH)
    state.topic = "calculus"
    state.background = "algebra"
    state.ladder = [
        {"id": "limits", "title": "Limits", "description": ""},
        {"id": "derivatives", "title": "Derivatives", "description": ""},
    ]
    state.boundary_index = 1
    state.probe_records = [
        ProbeRecord(
            concept_id="limits", concept_title="Limits",
            question="What is $\\lim_{x\\to 0} x$?", kind="multiple_choice",
            choices=["0", "1"], user_answer="A", correct=True, feedback="Yes.",
        )
    ]
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="derivatives", title="Derivatives"))
    dag.add_node(ConceptNode(id="chain_rule", title="Chain rule"))
    dag.add_edge("derivatives", "chain_rule")
    dag.nodes["derivatives"].status = STATUS_COMPLETED
    state.dag = dag
    state.fact_check_notes = "All verified."
    state.lessons = [
        LessonRecord(
            node_id="derivatives", title="Derivatives",
            explanation="The derivative is $$f'(x)=\\lim_{h\\to 0}\\frac{f(x+h)-f(x)}{h}$$",
            svg_path="assets/001_derivatives.svg",
            question="What is $f'(x)$ for $f(x)=x^2$?",
            kind="short_answer", choices=[],
            user_answer="2x", passed=True, feedback="Correct.",
        )
    ]
    return state


def test_render_contains_all_sections():
    text = markdown_log.render(build_state())
    assert "# Learning Session: calculus" in text
    assert "## Knowledge Probe" in text
    assert "Q1. Limits — correct" in text
    assert "```mermaid" in text
    assert "derivatives --> chain_rule" in text
    assert "**Progress:** 1/2 concepts" in text
    assert "## Lessons" in text
    assert "$$f'(x)" in text  # LaTeX preserved verbatim
    assert "![Derivatives](assets/001_derivatives.svg)" in text
    assert "**Check:**" in text
    assert "> **Verifier notes:** All verified." in text
    assert "knows up to *Limits*; learning starts at *Derivatives*" in text


def test_render_probe_in_progress():
    state = SessionState(name="s", phase=PHASE_PROBE)
    state.topic = "calculus"
    text = markdown_log.render(state)
    assert "_Probing in progress..._" in text


def test_render_done_has_completion_section():
    state = build_state()
    state.phase = PHASE_DONE
    assert "## Session Complete" in markdown_log.render(state)


def test_write_creates_log_file(tmp_path):
    store = SessionStore(tmp_path)
    state = build_state()
    markdown_log.write(store, state)
    log = store.log_path("s")
    assert log.exists()
    assert log.read_text(encoding="utf-8").startswith("# Learning Session")
