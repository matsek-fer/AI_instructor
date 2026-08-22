import pytest

from ai_learner.dag import (
    STATUS_COMPLETED,
    STATUS_KNOWN,
    ConceptDAG,
    ConceptNode,
    slugify,
)
from ai_learner.errors import DAGError


def make_chain(*ids: str) -> ConceptDAG:
    dag = ConceptDAG()
    for node_id in ids:
        dag.add_node(ConceptNode(id=node_id, title=node_id.upper()))
    for parent, child in zip(ids, ids[1:]):
        dag.add_edge(parent, child)
    return dag


def test_slugify():
    assert slugify("The Chain Rule!") == "the_chain_rule"
    assert slugify("  ") == "node"


def test_duplicate_node_rejected():
    dag = make_chain("a")
    with pytest.raises(DAGError, match="duplicate"):
        dag.add_node(ConceptNode(id="a", title="A"))


def test_edge_to_unknown_node_rejected():
    dag = make_chain("a")
    with pytest.raises(DAGError, match="unknown node"):
        dag.add_edge("a", "ghost")


def test_self_edge_rejected():
    dag = make_chain("a")
    with pytest.raises(DAGError, match="self-edge"):
        dag.add_edge("a", "a")


def test_cycle_rejected():
    dag = make_chain("a", "b", "c")
    with pytest.raises(DAGError, match="cycle"):
        dag.add_edge("c", "a")


def test_topological_order_is_deterministic():
    dag = ConceptDAG()
    for node_id in ("root", "left", "right", "leaf"):
        dag.add_node(ConceptNode(id=node_id, title=node_id))
    dag.add_edge("root", "left")
    dag.add_edge("root", "right")
    dag.add_edge("left", "leaf")
    dag.add_edge("right", "leaf")
    assert dag.topological_order() == ["root", "left", "right", "leaf"]


def test_next_pending_walks_in_order():
    dag = make_chain("a", "b", "c")
    assert dag.next_pending().id == "a"
    dag.nodes["a"].status = STATUS_COMPLETED
    assert dag.next_pending().id == "b"
    dag.nodes["b"].status = STATUS_KNOWN
    dag.nodes["c"].status = STATUS_COMPLETED
    assert dag.next_pending() is None
    assert dag.is_complete()


def test_insert_remedial_sits_between_prereqs_and_target():
    dag = make_chain("a", "b", "c")
    dag.insert_remedial("c", ConceptNode(id="r", title="Remedial"))
    assert dag.topological_order() == ["a", "b", "r", "c"]
    assert dag.prerequisites("r") == {"b"}
    assert dag.prerequisites("c") == {"b", "r"}
    assert dag.nodes["r"].remedial


def test_mermaid_output():
    dag = make_chain("a", "b")
    dag.nodes["a"].status = STATUS_COMPLETED
    mermaid = dag.to_mermaid()
    assert mermaid.startswith("graph TD")
    assert 'a["A"]' in mermaid
    assert "a --> b" in mermaid
    assert "class a completed;" in mermaid
    assert "class b pending;" in mermaid


def test_mermaid_escapes_labels():
    dag = ConceptDAG()
    dag.add_node(ConceptNode(id="x", title='Bad "label" [here]'))
    mermaid = dag.to_mermaid()
    assert "#quot;" in mermaid  # inner quotes escaped
    assert "[here]" not in mermaid  # square brackets neutralized
    assert "(here)" in mermaid


def test_roundtrip_serialization():
    dag = make_chain("a", "b", "c")
    dag.nodes["b"].status = STATUS_COMPLETED
    dag.insert_remedial("c", ConceptNode(id="r", title="R"))
    restored = ConceptDAG.from_dict(dag.to_dict())
    assert restored.topological_order() == dag.topological_order()
    assert restored.nodes["b"].status == STATUS_COMPLETED
    assert restored.nodes["r"].remedial
    assert restored.prerequisites("c") == dag.prerequisites("c")
