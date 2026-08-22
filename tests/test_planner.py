import pytest

from ai_learner.errors import DAGError
from ai_learner.planner import Planner
from ai_learner.subagents.factcheck import ConceptVerdict, FactCheckReport

from conftest import FakeLLM

REPORT = FactCheckReport(
    verdicts=[ConceptVerdict(concept_id="x", accurate=False, issue="wrong", correction="right")],
    notes="One fix.",
)


def plan(nodes):
    return {"nodes": nodes}


def test_build_valid_dag():
    llm = FakeLLM([
        plan([
            {"id": "a", "title": "A", "description": "", "prerequisites": []},
            {"id": "b", "title": "B", "description": "", "prerequisites": ["a"]},
        ])
    ])
    dag = Planner(llm).build_dag("topic", [{"title": "known"}], [{"id": "a", "title": "A"}], REPORT)
    assert dag.topological_order() == ["a", "b"]
    assert dag.prerequisites("b") == {"a"}
    # Prompt carries known concepts and verifier corrections.
    assert "known" in llm.calls[0].prompt
    assert "wrong -> right" in llm.calls[0].prompt


def test_retry_on_cyclic_plan_then_succeed():
    llm = FakeLLM([
        plan([
            {"id": "a", "title": "A", "description": "", "prerequisites": ["b"]},
            {"id": "b", "title": "B", "description": "", "prerequisites": ["a"]},
        ]),
        plan([
            {"id": "a", "title": "A", "description": "", "prerequisites": []},
            {"id": "b", "title": "B", "description": "", "prerequisites": ["a"]},
        ]),
    ])
    dag = Planner(llm).build_dag("topic", [], [], REPORT)
    assert dag.topological_order() == ["a", "b"]
    assert "structurally invalid" in llm.calls[1].prompt


def test_gives_up_after_retries():
    cyclic = plan([
        {"id": "a", "title": "A", "description": "", "prerequisites": ["b"]},
        {"id": "b", "title": "B", "description": "", "prerequisites": ["a"]},
    ])
    llm = FakeLLM([cyclic, cyclic])
    with pytest.raises(DAGError, match="failed to produce a valid DAG"):
        Planner(llm, max_retries=1).build_dag("topic", [], [], REPORT)


def test_slug_collisions_and_messy_ids_are_normalized():
    llm = FakeLLM([
        plan([
            {"id": "The Chain Rule", "title": "Chain rule", "description": "", "prerequisites": []},
            {"id": "the_chain_rule", "title": "Other", "description": "",
             "prerequisites": ["The Chain Rule"]},
        ])
    ])
    dag = Planner(llm).build_dag("topic", [], [], REPORT)
    assert set(dag.nodes) == {"the_chain_rule", "the_chain_rule_2"}
    assert dag.prerequisites("the_chain_rule_2") == {"the_chain_rule"}


def test_self_prerequisite_is_ignored():
    llm = FakeLLM([
        plan([{"id": "a", "title": "A", "description": "", "prerequisites": ["a"]}])
    ])
    dag = Planner(llm).build_dag("topic", [], [], REPORT)
    assert dag.prerequisites("a") == set()
