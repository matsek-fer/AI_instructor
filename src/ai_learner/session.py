"""Session state: everything the tutor knows about one learning session.

State is a plain serializable structure persisted as ``state.json`` inside the
session directory, next to the live ``session.md`` log and an ``assets/``
folder for generated SVGs. Any run can be interrupted and resumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .dag import ConceptDAG
from .errors import DAGError, SessionError

# Version of the on-disk state.json format. Files written before the field
# existed are accepted on load (pre-1.0) and stamped on their next save.
STATE_SCHEMA_VERSION = "1.0"

# Session phases, in order.
PHASE_SETUP = "setup"
PHASE_PROBE = "probe"
PHASE_PLAN = "plan"
PHASE_TEACH = "teach"
PHASE_DONE = "done"

STATE_FILENAME = "state.json"
LOG_FILENAME = "session.md"
ASSETS_DIRNAME = "assets"
EXPERIENCE_FILENAME = "experience.md"

# `created_at` format; also what experience duration is derived from.
CREATED_AT_FORMAT = "%Y-%m-%d %H:%M UTC"


def _split_extras(cls, data: dict) -> tuple[dict, dict]:
    """Separate the keys a dataclass declares from everything else.

    Unknown keys — a co-frontend's bookkeeping, a third-party tool's
    annotations — are captured so `to_dict` can round-trip them verbatim:
    saving must never erase another tool's work.
    """
    known = {f.name for f in fields(cls)} - {"extras"}
    return (
        {k: v for k, v in data.items() if k in known},
        {k: v for k, v in data.items() if k not in known},
    )


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
    #: Unknown keys from other tools, preserved verbatim across save/load.
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k != "extras"}
        data.update(self.extras)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ProbeRecord":
        known, extras = _split_extras(cls, data)
        return cls(**known, extras=extras)


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
    #: Unknown keys from other tools, preserved verbatim across save/load.
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k != "extras"}
        data.update(self.extras)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "LessonRecord":
        known, extras = _split_extras(cls, data)
        return cls(**known, extras=extras)


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
    #: Unknown top-level keys from other tools, preserved verbatim.
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime(CREATED_AT_FORMAT)

    def next_asset_name(self, stem: str) -> str:
        """A fresh, unique filename (relative to the session dir) for an SVG."""
        self.asset_counter += 1
        return f"{ASSETS_DIRNAME}/{self.asset_counter:03d}_{slug_for_filename(stem)}.svg"

    def to_dict(self) -> dict:
        data = {
            "schema_version": STATE_SCHEMA_VERSION,
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
        data.update(self.extras)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        _, extras = _split_extras(cls, data)
        # The file's schema_version is metadata, not state: absent in pre-1.0
        # files, and always restamped with the current version on save.
        extras.pop("schema_version", None)
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
            extras=extras,
        )


def _minutes_since(created_at: str) -> int | None:
    """Whole minutes from `created_at` to now, or None when not derivable
    (unparseable timestamp, a clock that went backwards, or a sub-minute
    session — the experience schema floors duration_minutes at 1, so zero
    means "omit", never "0")."""
    try:
        start = datetime.strptime(created_at, CREATED_AT_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    minutes = int((datetime.now(timezone.utc) - start).total_seconds() // 60)
    return minutes if minutes >= 1 else None


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

    def experience_path(self, name: str) -> Path:
        return self.session_dir(name) / EXPERIENCE_FILENAME

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
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, DAGError) as exc:
            # DAGError covers structurally invalid graphs (dangling edges,
            # cycles) in files written by other tools — corruption all the same.
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

    def write_experience(self, state: SessionState) -> Path | None:
        """Emit the ecosystem experience bundle for a finished session.

        Returns the path when a file was written, or None when one already
        exists: the member may have edited it, so it is never overwritten.
        `rating` is deliberately absent — the harness cannot ask for one
        cheaply mid-flow; the member (or the skill frontend) adds it.
        """
        path = self.experience_path(state.name)
        if path.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "---",
            'schema_version: "1.0"',
            "type: experience",
            "tool: tutor",
            f'tool_version: "{__version__}"',
        ]
        minutes = _minutes_since(state.created_at)
        if minutes is not None:
            lines.append(f"duration_minutes: {minutes}")
        lines += [
            "consent_public: false",
            # Quoted so a slug like "true" or "42" stays a YAML string.
            f'session_ref: "{state.name}"',
            "---",
            "",
        ]

        taught = len(state.lessons)
        flagged = len(state.dag.review_ids()) if state.dag is not None else 0
        summary = f"Tutoring session on {state.topic or state.name}: {taught} teaching step(s)"
        if flagged:
            summary += f", {flagged} concept(s) left marked for review"
        summary += "."
        lines += [
            summary,
            "",
            "<!-- Written by the tutor harness. Add your own notes below —",
            "what happened, what was confusing, what could be better. This file",
            "stays local unless you choose to submit it. -->",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def write_asset(self, state: SessionState, relative_path: str, content: str) -> Path:
        path = self.session_dir(state.name) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
