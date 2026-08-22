"""Session state: everything the tutor knows about one learning session.

State is a plain serializable structure persisted as ``state.json`` inside the
session directory, next to the live ``session.md`` log and an ``assets/``
folder for generated SVGs. Any run can be interrupted and resumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .dag import ConceptDAG
from .errors import SessionError

# Session phases, in order.
PHASE_SETUP = "setup"
PHASE_PROBE = "probe"
PHASE_PLAN = "plan"
PHASE_TEACH = "teach"
PHASE_DONE = "done"

STATE_FILENAME = "state.json"
LOG_FILENAME = "session.md"
ASSETS_DIRNAME = "assets"


@dataclass
class ProbeRecord:
    """One diagnostic question asked during the probing phase."""

    concept_id: str
    concept_title: str
    question: str
    kind: str  # "multiple_choice" | "short_answer"
    choices: list[str]
    user_answer: str = ""
    correct: bool | None = None
    feedback: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "ProbeRecord":
        return cls(**data)


@dataclass
class LessonRecord:
    """One taught step: explanation, optional visual, assessment, outcome."""

    node_id: str
    title: str
    explanation: str
    svg_path: str = ""  # relative to the session dir, e.g. "assets/step_1.svg"
    question: str = ""
    kind: str = "short_answer"
    choices: list[str] = field(default_factory=list)
    user_answer: str = ""
    passed: bool | None = None
    feedback: str = ""
    #: Non-empty when the verifier still flagged issues on the final draft.
    caution: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "LessonRecord":
        return cls(**data)


@dataclass
class SessionState:
    name: str
    created_at: str = ""
    phase: str = PHASE_SETUP
    topic: str = ""
    background: str = ""
    # Prerequisite ladder produced at the start of probing, ordered from
    # foundational (index 0) to advanced.
    ladder: list[dict] = field(default_factory=list)
    probe_records: list[ProbeRecord] = field(default_factory=list)
    # Index into `ladder` of the first concept the learner does NOT know.
    boundary_index: int | None = None
    fact_check_notes: str = ""
    dag: ConceptDAG | None = None
    lessons: list[LessonRecord] = field(default_factory=list)
    asset_counter: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def next_asset_name(self, stem: str) -> str:
        """A fresh, unique filename (relative to the session dir) for an SVG."""
        self.asset_counter += 1
        return f"{ASSETS_DIRNAME}/{self.asset_counter:03d}_{slug_for_filename(stem)}.svg"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "phase": self.phase,
            "topic": self.topic,
            "background": self.background,
            "ladder": self.ladder,
            "probe_records": [r.to_dict() for r in self.probe_records],
            "boundary_index": self.boundary_index,
            "fact_check_notes": self.fact_check_notes,
            "dag": self.dag.to_dict() if self.dag is not None else None,
            "lessons": [lesson.to_dict() for lesson in self.lessons],
            "asset_counter": self.asset_counter,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        return cls(
            name=data["name"],
            created_at=data.get("created_at", ""),
            phase=data.get("phase", PHASE_SETUP),
            topic=data.get("topic", ""),
            background=data.get("background", ""),
            ladder=data.get("ladder", []),
            probe_records=[ProbeRecord.from_dict(r) for r in data.get("probe_records", [])],
            boundary_index=data.get("boundary_index"),
            fact_check_notes=data.get("fact_check_notes", ""),
            dag=ConceptDAG.from_dict(data["dag"]) if data.get("dag") else None,
            lessons=[LessonRecord.from_dict(r) for r in data.get("lessons", [])],
            asset_counter=data.get("asset_counter", 0),
        )


def slug_for_filename(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "session"


class SessionStore:
    """Filesystem layout and persistence for sessions under a vault directory."""

    def __init__(self, vault: Path):
        self.vault = Path(vault)

    def session_dir(self, name: str) -> Path:
        # Normalizing here (idempotent for already-created names) means every
        # lookup matches what `create` produced — the name typed at `start`
        # resolves on `resume`/`status` — and a hostile name like "../../x"
        # can never escape the vault.
        return self.vault / slug_for_filename(name)

    def assets_dir(self, name: str) -> Path:
        return self.session_dir(name) / ASSETS_DIRNAME

    def log_path(self, name: str) -> Path:
        return self.session_dir(name) / LOG_FILENAME

    def create(self, name: str | None = None) -> SessionState:
        if not name:
            name = datetime.now(timezone.utc).strftime("session-%Y%m%d-%H%M%S")
        name = slug_for_filename(name)
        directory = self.session_dir(name)
        if (directory / STATE_FILENAME).exists():
            raise SessionError(f"session already exists: {name}")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ASSETS_DIRNAME).mkdir(exist_ok=True)
        state = SessionState(name=name)
        self.save(state)
        return state

    def save(self, state: SessionState) -> None:
        directory = self.session_dir(state.name)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / STATE_FILENAME
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    def load(self, name: str) -> SessionState:
        path = self.session_dir(name) / STATE_FILENAME
        if not path.exists():
            raise SessionError(f"no such session: {name}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SessionError(f"corrupt session state in {path}: {exc}") from exc

    def list_sessions(self) -> list[str]:
        if not self.vault.exists():
            return []
        return sorted(
            entry.name
            for entry in self.vault.iterdir()
            if entry.is_dir() and (entry / STATE_FILENAME).exists()
        )

    def latest(self) -> str | None:
        """Most recently touched *loadable* session (corrupt ones are skipped,
        so one damaged state.json never bricks a bare `resume`)."""
        loadable = []
        for name in self.list_sessions():
            try:
                self.load(name)
            except SessionError:
                continue
            loadable.append(name)
        if not loadable:
            return None
        return max(
            loadable,
            key=lambda name: (self.session_dir(name) / STATE_FILENAME).stat().st_mtime,
        )

    def write_asset(self, state: SessionState, relative_path: str, content: str) -> Path:
        path = self.session_dir(state.name) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
