import json

import pytest

from ai_learner.dag import ConceptDAG, ConceptNode
from ai_learner.errors import SessionError
from ai_learner.session import (
    PHASE_TEACH,
    LessonRecord,
    ProbeRecord,
    SessionStore,
)


def test_create_save_load_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "vault")
    state = store.create("My Test Session")
    assert state.name == "my-test-session"

    state.topic = "linear algebra"
    state.background = "high-school math"
    state.phase = PHASE_TEACH
    state.ladder = [{"id": "vectors", "title": "Vectors", "description": ""}]
    state.boundary_index = 0
    state.probe_records.append(
        ProbeRecord(
            concept_id="vectors", concept_title="Vectors", question="Q?",
            kind="short_answer", choices=[], user_answer="ans",
            correct=False, feedback="fb",
        )
    )
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="dot", title="Dot product"))
    state.dag = dag
    state.lessons.append(
        LessonRecord(node_id="dot", title="Dot product", explanation="Step.")
    )
    store.save(state)

    loaded = store.load("my-test-session")
    assert loaded.topic == "linear algebra"
    assert loaded.phase == PHASE_TEACH
    assert loaded.probe_records[0].correct is False
    assert loaded.dag.nodes["dot"].title == "Dot product"
    assert loaded.lessons[0].explanation == "Step."


def test_create_duplicate_rejected(tmp_path):
    store = SessionStore(tmp_path)
    store.create("dup")
    with pytest.raises(SessionError, match="already exists"):
        store.create("dup")


def test_load_missing_session(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(SessionError, match="no such session"):
        store.load("ghost")


def test_load_corrupt_state(tmp_path):
    store = SessionStore(tmp_path)
    state = store.create("bad")
    (store.session_dir(state.name) / "state.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SessionError, match="corrupt"):
        store.load("bad")


def test_list_and_latest(tmp_path):
    store = SessionStore(tmp_path)
    assert store.list_sessions() == []
    assert store.latest() is None
    a = store.create("alpha")
    b = store.create("beta")
    assert store.list_sessions() == ["alpha", "beta"]
    store.save(a)  # touch alpha last
    assert store.latest() == "alpha"
    store.save(b)
    assert store.latest() == "beta"


def test_asset_naming_and_writing(tmp_path):
    store = SessionStore(tmp_path)
    state = store.create("assets")
    first = state.next_asset_name("Chain Rule")
    second = state.next_asset_name("Chain Rule")
    assert first == "assets/001_chain-rule.svg"
    assert second == "assets/002_chain-rule.svg"
    path = store.write_asset(state, first, "<svg/>")
    assert path.read_text(encoding="utf-8") == "<svg/>"


def test_state_file_is_valid_json(tmp_path):
    store = SessionStore(tmp_path)
    state = store.create("plain")
    raw = (store.session_dir(state.name) / "state.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["name"] == "plain"
    assert data["phase"] == "setup"
