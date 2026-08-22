"""Concept dependency graph (DAG) with Mermaid rendering.

The learning plan is a directed acyclic graph of concepts. Edges point from a
prerequisite to the concept that depends on it. The harness enforces
acyclicity structurally, so the model can never "jump" the learner past a
prerequisite: teaching order is always a topological order of this graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from .errors import DAGError

# Node lifecycle: pending -> active -> completed. Nodes below the learner's
# knowledge boundary are marked "known" and are never taught.
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_KNOWN = "known"

_VALID_STATUSES = {STATUS_PENDING, STATUS_ACTIVE, STATUS_COMPLETED, STATUS_KNOWN}


def slugify(text: str) -> str:
    """Reduce arbitrary text to a mermaid-safe node identifier."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "node"


@dataclass
class ConceptNode:
    id: str
    title: str
    description: str = ""
    status: str = STATUS_PENDING
    remedial: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "remedial": self.remedial,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConceptNode":
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            status=data.get("status", STATUS_PENDING),
            remedial=data.get("remedial", False),
        )


@dataclass
class ConceptDAG:
    nodes: dict[str, ConceptNode] = field(default_factory=dict)
    # edges[b] = set of prerequisites of b (edges point prerequisite -> dependent)
    _parents: dict[str, set[str]] = field(default_factory=dict)
    # Insertion order of node ids; used as the tie-breaker so topological order
    # is deterministic and remedial insertions land where they were spliced in.
    _order: list[str] = field(default_factory=list)

    # -- construction -----------------------------------------------------

    def add_node(self, node: ConceptNode, index: int | None = None) -> None:
        if node.id in self.nodes:
            raise DAGError(f"duplicate node id: {node.id}")
        if node.status not in _VALID_STATUSES:
            raise DAGError(f"invalid status {node.status!r} on node {node.id}")
        self.nodes[node.id] = node
        self._parents[node.id] = set()
        if index is None:
            self._order.append(node.id)
        else:
            self._order.insert(index, node.id)

    def add_edge(self, prerequisite: str, dependent: str) -> None:
        for node_id in (prerequisite, dependent):
            if node_id not in self.nodes:
                raise DAGError(f"edge references unknown node: {node_id}")
        if prerequisite == dependent:
            raise DAGError(f"self-edge on node: {prerequisite}")
        if self._reaches(dependent, prerequisite):
            raise DAGError(
                f"edge {prerequisite} -> {dependent} would create a cycle"
            )
        self._parents[dependent].add(prerequisite)

    def _reaches(self, start: str, target: str) -> bool:
        """True if `target` is reachable from `start` following prerequisite->dependent edges."""
        stack, seen = [start], set()
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(child for child in self.nodes if current in self._parents[child])
        return False

    # -- queries ----------------------------------------------------------

    def prerequisites(self, node_id: str) -> set[str]:
        return set(self._parents[node_id])

    def topological_order(self) -> list[str]:
        """Kahn's algorithm; ties broken by node insertion order (deterministic)."""
        indegree = {nid: len(self._parents[nid]) for nid in self.nodes}
        rank = {nid: i for i, nid in enumerate(self._order)}
        ready = sorted((nid for nid, d in indegree.items() if d == 0), key=rank.__getitem__)
        result: list[str] = []
        while ready:
            current = ready.pop(0)
            result.append(current)
            for child in self.nodes:
                if current in self._parents[child]:
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        ready.append(child)
            ready.sort(key=rank.__getitem__)
        if len(result) != len(self.nodes):
            raise DAGError("graph contains a cycle")
        return result

    def next_pending(self) -> ConceptNode | None:
        """The next node to teach: first pending/active node in topological order."""
        for node_id in self.topological_order():
            node = self.nodes[node_id]
            if node.status in (STATUS_PENDING, STATUS_ACTIVE):
                return node
        return None

    def completed_ids(self) -> list[str]:
        return [nid for nid in self.topological_order()
                if self.nodes[nid].status in (STATUS_COMPLETED, STATUS_KNOWN)]

    def is_complete(self) -> bool:
        return self.next_pending() is None

    def __iter__(self) -> Iterator[ConceptNode]:
        return (self.nodes[nid] for nid in self.topological_order())

    def __len__(self) -> int:
        return len(self.nodes)

    # -- mutation during teaching ----------------------------------------

    def insert_remedial(self, before_id: str, node: ConceptNode) -> None:
        """Splice a remedial concept in as a new prerequisite of `before_id`.

        The remedial node inherits the target's current prerequisites so it
        sits between them and the struggling concept.
        """
        if before_id not in self.nodes:
            raise DAGError(f"unknown node: {before_id}")
        node.remedial = True
        inherited = set(self._parents[before_id])
        position = self._order.index(before_id)
        self.add_node(node, index=position)
        for parent in inherited:
            self.add_edge(parent, node.id)
        self.add_edge(node.id, before_id)

    # -- rendering --------------------------------------------------------

    def to_mermaid(self) -> str:
        """Render the plan as a Mermaid flowchart with per-status styling."""
        lines = ["graph TD"]
        order = self.topological_order()
        for node_id in order:
            node = self.nodes[node_id]
            label = _mermaid_escape(node.title)
            marker = " *" if node.remedial else ""
            lines.append(f'    {node_id}["{label}{marker}"]')
        for node_id in order:
            for parent in sorted(self._parents[node_id]):
                lines.append(f"    {parent} --> {node_id}")
        lines.append("    classDef known fill:#d3f9d8,stroke:#2b8a3e,color:#000;")
        lines.append("    classDef completed fill:#a5d8ff,stroke:#1971c2,color:#000;")
        lines.append("    classDef active fill:#ffe066,stroke:#e67700,color:#000;")
        lines.append("    classDef pending fill:#f1f3f5,stroke:#868e96,color:#000;")
        for status in (STATUS_KNOWN, STATUS_COMPLETED, STATUS_ACTIVE, STATUS_PENDING):
            members = [nid for nid in order if self.nodes[nid].status == status]
            if members:
                lines.append(f"    class {','.join(members)} {status};")
        return "\n".join(lines)

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nodes": [self.nodes[nid].to_dict() for nid in self._order],
            "edges": sorted(
                [parent, child]
                for child in self.nodes
                for parent in self._parents[child]
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConceptDAG":
        dag = cls()
        for node_data in data.get("nodes", []):
            dag.add_node(ConceptNode.from_dict(node_data))
        for parent, child in data.get("edges", []):
            dag.add_edge(parent, child)
        return dag


def _mermaid_escape(text: str) -> str:
    """Escape characters that break Mermaid node labels."""
    return text.replace('"', "#quot;").replace("[", "(").replace("]", ")")
