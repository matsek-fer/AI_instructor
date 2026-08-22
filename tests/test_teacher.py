from ai_learner.dag import STATUS_COMPLETED, ConceptDAG, ConceptNode
from ai_learner.subagents.factcheck import FactChecker
from ai_learner.teacher import Teacher

from conftest import FakeLLM

STEP = {
    "explanation": "One step: $x^2$ differentiates to $2x$.",
    "needs_visual": False,
    "visual_description": "",
    "question": "What is the derivative of $x^3$?",
    "kind": "short_answer",
    "choices": [],
}
SOUND = {"sound": True, "issues": []}


def make_dag():
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="basics", title="Basics", status=STATUS_COMPLETED))
    dag.add_node(ConceptNode(id="power_rule", title="Power rule"))
    dag.add_edge("basics", "power_rule")
    return dag


def make_teacher(llm):
    return Teacher(llm, FactChecker(llm), factcheck_max_retries=2)


def test_teach_verifies_step_before_presenting():
    llm = FakeLLM([STEP, SOUND])
    dag = make_dag()
    step = make_teacher(llm).teach("calculus", dag.nodes["power_rule"], dag)
    assert step.explanation == STEP["explanation"]
    # Call 1 generates, call 2 fact-checks; completed concepts are in context.
    assert "Basics" in llm.calls[0].prompt
    assert "Teaching step to verify" in llm.calls[1].prompt


def test_teach_regenerates_when_factcheck_flags_errors():
    bad_step = dict(STEP, explanation="Wrong: $x^2$ differentiates to $3x$.")
    llm = FakeLLM([
        bad_step,
        {"sound": False, "issues": ["derivative of $x^2$ is $2x$, not $3x$"]},
        STEP,      # regenerated with the issues in context
        SOUND,
    ])
    dag = make_dag()
    step = make_teacher(llm).teach("calculus", dag.nodes["power_rule"], dag)
    assert step.explanation == STEP["explanation"]
    assert "rejected by the verifier" in llm.calls[2].prompt


def test_teach_reteach_feedback_reaches_prompt():
    llm = FakeLLM([STEP, SOUND])
    dag = make_dag()
    make_teacher(llm).teach(
        "calculus", dag.nodes["power_rule"], dag,
        prior_attempt_feedback="Confused the exponent.",
    )
    assert "Confused the exponent." in llm.calls[0].prompt
    assert "different angle" in llm.calls[0].prompt


def test_degenerate_multiple_choice_becomes_short_answer():
    weird = dict(STEP, kind="multiple_choice", choices=["only"])
    llm = FakeLLM([weird, SOUND])
    dag = make_dag()
    step = make_teacher(llm).teach("calculus", dag.nodes["power_rule"], dag)
    assert step.kind == "short_answer"
    assert step.choices == []


def test_assess_returns_remediation():
    llm = FakeLLM([
        {
            "passed": False,
            "feedback": "You applied the rule to the base, not the exponent.",
            "remedial_concepts": [
                {"id": "exponents", "title": "Exponents", "description": "power basics"}
            ],
        }
    ])
    dag = make_dag()
    step_obj = make_teacher(FakeLLM([STEP, SOUND])).teach(
        "calculus", make_dag().nodes["power_rule"], make_dag()
    )
    result = make_teacher(llm).assess("calculus", dag.nodes["power_rule"], step_obj, "3x")
    assert not result.passed
    assert result.remedial_concepts[0]["id"] == "exponents"
