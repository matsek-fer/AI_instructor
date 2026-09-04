"""State-format guarantees: schema_version stamping, unknown-key round-trips,
and the experience.md bundle emitted at session end."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ai_learner.dag import ConceptDAG, ConceptNode
from ai_learner.session import (
    CREATED_AT_FORMAT,
    PHASE_DONE,
    STATE_SCHEMA_VERSION,
    SessionState,
    SessionStore,
)


def make_state_dict(**overrides) -> dict:
    data = {
        "name": "calculus",
        "created_at": "2026-08-23 10:00 UTC",
        "phase": "teach",
        "topic": "Calculus",
        "background": "",
        "ladder": [],
        "probe_records": [
            {
                "concept_id": "limits",
                "concept_title": "Limits",
                "question": "?",
                "kind": "short_answer",
                "choices": [],
                "user_answer": "0",
                "correct": True,
                "feedback": "ok",
            }
        ],
        "boundary_index": 0,
        "fact_check_notes": "",
        "dag": {
            "nodes": [
                {"id": "a", "title": "A", "description": "", "status": "pending",
                 "remedial": False, "needs_review": False},
            ],
            "edges": [],
        },
        "lessons": [
            {
                "node_id": "a",
                "title": "A",
                "explanation": "x",
                "svg_path": "",
                "question": "?",
                "kind": "short_answer",
                "choices": [],
                "user_answer": "y",
                "passed": True,
                "feedback": "ok",
                "caution": "",
            }
        ],
        "asset_counter": 0,
    }
    data.update(overrides)
    return data


def store_roundtrip(tmp_path, data: dict) -> dict:
    """Write raw JSON, load through the store, save, and reread the file."""
    store = SessionStore(tmp_path / "vault")
    directory = store.session_dir(data["name"])
    directory.mkdir(parents=True)
    (directory / "state.json").write_text(json.dumps(data), encoding="utf-8")
    state = store.load(data["name"])
    store.save(state)
    return json.loads((directory / "state.json").read_text(encoding="utf-8"))


def test_save_stamps_schema_version(tmp_path):
    store = SessionStore(tmp_path / "vault")
    state = store.create("fresh")
    on_disk = json.loads(
        (store.session_dir(state.name) / "state.json").read_text(encoding="utf-8")
    )
    assert on_disk["schema_version"] == STATE_SCHEMA_VERSION


def test_pre_1_0_state_loads_and_upgrades_on_save(tmp_path):
    data = make_state_dict()
    assert "schema_version" not in data
    saved = store_roundtrip(tmp_path, data)
    assert saved["schema_version"] == STATE_SCHEMA_VERSION
    # The absent field must not leak into preserved unknown keys either.
    assert list(saved).count("schema_version") == 1


def test_unknown_top_level_keys_round_trip(tmp_path):
    data = make_state_dict()
    data["search"] = {"low": 0, "high": 5}
    data["x_reviewer"] = "someone"
    saved = store_roundtrip(tmp_path, data)
    assert saved["search"] == {"low": 0, "high": 5}
    assert saved["x_reviewer"] == "someone"


def test_unknown_keys_round_trip_in_records_and_dag(tmp_path):
    data = make_state_dict()
    data["probe_records"][0]["x_probe_note"] = {"nested": [1, 2]}
    data["lessons"][0]["x_lesson_note"] = "kept"
    data["dag"]["nodes"][0]["x_node_note"] = 7
    data["dag"]["x_dag_note"] = True
    saved = store_roundtrip(tmp_path, data)
    assert saved["probe_records"][0]["x_probe_note"] == {"nested": [1, 2]}
    assert saved["lessons"][0]["x_lesson_note"] == "kept"
    assert saved["dag"]["nodes"][0]["x_node_note"] == 7
    assert saved["dag"]["x_dag_note"] is True


def test_known_keys_still_load_into_fields(tmp_path):
    """Preservation must not swallow declared keys into the extras bag."""
    saved = store_roundtrip(tmp_path, make_state_dict(x_extra="e"))
    store = SessionStore(tmp_path / "vault")
    state = store.load("calculus")
    assert state.topic == "Calculus"
    assert state.probe_records[0].correct is True
    assert state.lessons[0].passed is True
    assert state.extras == {"x_extra": "e"}
    assert saved["topic"] == "Calculus"


def frontmatter_of(path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    fm = {}
    for line in lines[1:end]:
        key, _, value = line.partition(": ")
        fm[key] = value
    return fm


def test_experience_written_when_done(tmp_path):
    store = SessionStore(tmp_path / "vault")
    state = SessionState.from_dict(make_state_dict(phase=PHASE_DONE))
    # A created_at half an hour in the past makes duration derivable.
    state.created_at = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    ).strftime(CREATED_AT_FORMAT)
    path = store.write_experience(state)
    assert path == store.experience_path(state.name)

    fm = frontmatter_of(path)
    assert fm["schema_version"] == '"1.0"'
    assert fm["type"] == "experience"
    assert fm["tool"] == "tutor"
    assert fm["tool_version"].strip('"')  # non-empty package version
    assert fm["consent_public"] == "false"
    assert fm["session_ref"] == '"calculus"'
    assert "rating" not in fm
    assert 29 <= int(fm["duration_minutes"]) <= 31


def test_experience_duration_omitted_for_subminute_session(tmp_path):
    # The reviewer caught this boundary: a session finishing in under a
    # minute must omit the field — the spec schema floors it at 1, and
    # "duration_minutes: 0" is a spec-invalid bundle.
    store = SessionStore(tmp_path / "vault")
    state = SessionState.from_dict(make_state_dict(phase=PHASE_DONE))
    state.created_at = datetime.now(timezone.utc).strftime(CREATED_AT_FORMAT)
    fm = frontmatter_of(store.write_experience(state))
    assert "duration_minutes" not in fm


def test_experience_duration_omitted_when_not_derivable(tmp_path):
    store = SessionStore(tmp_path / "vault")
    state = SessionState.from_dict(make_state_dict(created_at="not a timestamp"))
    fm = frontmatter_of(store.write_experience(state))
    assert "duration_minutes" not in fm


def test_experience_never_overwritten(tmp_path):
    store = SessionStore(tmp_path / "vault")
    state = SessionState.from_dict(make_state_dict())
    edited = "---\nrating: 5\n---\nmy own words\n"
    path = store.experience_path(state.name)
    path.parent.mkdir(parents=True)
    path.write_text(edited, encoding="utf-8")
    assert store.write_experience(state) is None
    assert path.read_text(encoding="utf-8") == edited


def test_dag_object_roundtrip_preserves_extras():
    dag = ConceptDAG.from_dict(
        {
            "nodes": [
                {"id": "n", "title": "N", "description": "", "status": "pending",
                 "remedial": False, "needs_review": False, "x_hint": "h"},
            ],
            "edges": [],
            "x_meta": 1,
        }
    )
    out = dag.to_dict()
    assert out["x_meta"] == 1
    assert out["nodes"][0]["x_hint"] == "h"
