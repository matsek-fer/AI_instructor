import pytest

from ai_learner.errors import StructuredOutputError
from ai_learner.probe import BoundarySearch, ProbeModule
from ai_learner.session import ProbeRecord

from conftest import FakeLLM


# -- binary search ---------------------------------------------------------

@pytest.mark.parametrize("size", range(1, 9))
def test_boundary_search_finds_every_boundary(size):
    """For a learner who knows exactly the first k concepts, the search must
    converge on boundary == k, for every k."""
    for known in range(size + 1):
        search = BoundarySearch(size)
        questions = 0
        while not search.done:
            index = search.next_index()
            search.record(index, correct=(index < known))
            questions += 1
        assert search.boundary == known
        assert questions <= size.bit_length() + 1  # O(log n)


def test_boundary_search_guards():
    with pytest.raises(ValueError):
        BoundarySearch(0)
    search = BoundarySearch(1)
    with pytest.raises(ValueError):
        _ = search.boundary  # not converged yet
    search.record(0, True)
    with pytest.raises(ValueError):
        search.next_index()  # already converged
    assert search.boundary == 1


# -- ladder generation -----------------------------------------------------

def test_generate_ladder_slugifies_and_dedupes():
    llm = FakeLLM([
        {
            "concepts": [
                {"id": "Chain Rule!", "title": "Chain rule", "description": "d1"},
                {"id": "chain_rule", "title": "Chain rule again", "description": "d2"},
                {"id": "", "title": "Limits", "description": "d3"},
            ]
        }
    ])
    ladder = ProbeModule(llm).generate_ladder("calculus", "some algebra")
    ids = [c["id"] for c in ladder]
    assert ids == ["chain_rule", "chain_rule_2", "limits"]
    assert "calculus" in llm.calls[0].prompt
    assert "some algebra" in llm.calls[0].prompt


def test_generate_ladder_rejects_empty():
    llm = FakeLLM([{"concepts": []}])
    with pytest.raises(StructuredOutputError):
        ProbeModule(llm).generate_ladder("calculus", "")


# -- question generation ---------------------------------------------------

def test_ask_question_multiple_choice():
    llm = FakeLLM([
        {"question": "What is $2+2$?", "kind": "multiple_choice", "choices": ["3", "4", "5"]}
    ])
    record = ProbeModule(llm).ask_question(
        "arithmetic", "", {"id": "add", "title": "Addition", "description": ""}, []
    )
    assert record.kind == "multiple_choice"
    assert sorted(record.choices) == ["3", "4", "5"]  # order is shuffled
    assert record.concept_id == "add"


def test_ask_question_falls_back_to_short_answer_on_degenerate_choices():
    llm = FakeLLM([
        {"question": "Explain X.", "kind": "multiple_choice", "choices": ["only one"]}
    ])
    record = ProbeModule(llm).ask_question(
        "topic", "", {"id": "x", "title": "X", "description": ""}, []
    )
    assert record.kind == "short_answer"
    assert record.choices == []


def test_ask_question_includes_history():
    llm = FakeLLM([
        {"question": "Q2", "kind": "short_answer", "choices": []}
    ])
    prior = ProbeRecord(
        concept_id="a", concept_title="A", question="Q1",
        kind="short_answer", choices=[], correct=True,
    )
    ProbeModule(llm).ask_question(
        "topic", "", {"id": "b", "title": "B", "description": ""}, [prior]
    )
    assert "Q1" in llm.calls[0].prompt


# -- evaluation ------------------------------------------------------------

def test_evaluate_updates_record_and_letters_choices():
    llm = FakeLLM([{"correct": True, "feedback": "Right."}])
    record = ProbeRecord(
        concept_id="add", concept_title="Addition",
        question="What is 2+2?", kind="multiple_choice", choices=["3", "4"],
    )
    ProbeModule(llm).evaluate("arithmetic", record, "B")
    assert record.correct is True
    assert record.user_answer == "B"
    assert record.feedback == "Right."
    assert "A. 3" in llm.calls[0].prompt
    assert "B. 4" in llm.calls[0].prompt
