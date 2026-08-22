"""Live-updating Markdown session log (Obsidian-compatible).

The whole file is re-rendered from ``SessionState`` on every update, so the
log is always a consistent projection of the state — never an append-only
stream that can drift. LaTeX stays as ``$...$`` / ``$$...$$``, the plan is an
inline Mermaid block, and generated SVGs are embedded with image links
relative to the note.
"""

from __future__ import annotations

from .session import (
    PHASE_DONE,
    PHASE_PLAN,
    PHASE_PROBE,
    PHASE_TEACH,
    SessionState,
    SessionStore,
)

_CHOICE_LETTERS = "ABCDEFGHIJ"


def render(state: SessionState) -> str:
    parts = [_header(state)]
    if state.probe_records or state.phase in (PHASE_PROBE, PHASE_PLAN, PHASE_TEACH, PHASE_DONE):
        parts.append(_probe_section(state))
    if state.dag is not None:
        parts.append(_plan_section(state))
    if state.lessons:
        parts.append(_lessons_section(state))
    if state.phase == PHASE_DONE:
        parts.append(_completion_section(state))
    return "\n\n".join(part for part in parts if part) + "\n"


def write(store: SessionStore, state: SessionState) -> None:
    path = store.log_path(state.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(render(state), encoding="utf-8")
    tmp.replace(path)


def _header(state: SessionState) -> str:
    topic = state.topic or "(topic pending)"
    lines = [
        f"# Learning Session: {topic}",
        "",
        f"- **Session:** `{state.name}`",
        f"- **Started:** {state.created_at}",
        f"- **Phase:** {state.phase}",
    ]
    if state.background:
        lines.append(f"- **Background:** {state.background}")
    return "\n".join(lines)


def _probe_section(state: SessionState) -> str:
    lines = ["## Knowledge Probe", ""]
    if not state.probe_records:
        lines.append("_Probing in progress..._")
        return "\n".join(lines)
    for i, record in enumerate(state.probe_records, 1):
        verdict = "?" if record.correct is None else ("correct" if record.correct else "incorrect")
        lines.append(f"### Q{i}. {record.concept_title} — {verdict}")
        lines.append("")
        lines.append(record.question)
        if record.choices:
            lines.append("")
            for letter, choice in zip(_CHOICE_LETTERS, record.choices):
                lines.append(f"- **{letter}.** {choice}")
        if record.user_answer:
            lines.append("")
            lines.append(f"> **Answer:** {record.user_answer}")
        if record.feedback:
            lines.append(f"> {record.feedback}")
        lines.append("")
    if state.boundary_index is not None:
        boundary = _boundary_label(state)
        lines.append(f"**Knowledge boundary:** {boundary}")
    return "\n".join(lines).rstrip()


def _boundary_label(state: SessionState) -> str:
    idx = state.boundary_index
    if idx is None:
        return "not located yet"
    if idx >= len(state.ladder):
        return "the learner already knows every probed prerequisite"
    first_unknown = state.ladder[idx].get("title", state.ladder[idx].get("id", "?"))
    if idx == 0:
        return f"starting from the foundations ({first_unknown})"
    last_known = state.ladder[idx - 1].get("title", "?")
    return f"knows up to *{last_known}*; learning starts at *{first_unknown}*"


def _plan_section(state: SessionState) -> str:
    lines = ["## Learning Plan", ""]
    if state.fact_check_notes:
        lines.append(f"> **Verifier notes:** {state.fact_check_notes}")
        lines.append("")
    lines.append("```mermaid")
    lines.append(state.dag.to_mermaid())
    lines.append("```")
    total = len(state.dag)
    done = len(state.dag.completed_ids())
    flagged = state.dag.review_ids()
    lines.append("")
    progress = f"**Progress:** {done}/{total} concepts"
    if flagged:
        progress += f" ({len(flagged)} marked for review)"
    lines.append(progress)
    return "\n".join(lines)


def _lessons_section(state: SessionState) -> str:
    lines = ["## Lessons"]
    for i, lesson in enumerate(state.lessons, 1):
        lines.append("")
        lines.append(f"### {i}. {lesson.title}")
        lines.append("")
        lines.append(lesson.explanation.strip())
        if lesson.svg_path:
            lines.append("")
            lines.append(f"![{lesson.title}]({lesson.svg_path})")
        if lesson.question:
            lines.append("")
            lines.append(f"**Check:** {lesson.question}")
            if lesson.choices:
                for letter, choice in zip(_CHOICE_LETTERS, lesson.choices):
                    lines.append(f"- **{letter}.** {choice}")
        if lesson.caution:
            lines.append("")
            lines.append(f"> ⚠️ **Caution:** {lesson.caution}")
        if lesson.user_answer:
            lines.append("")
            verdict = "?" if lesson.passed is None else ("passed" if lesson.passed else "not yet")
            lines.append(f"> **Answer:** {lesson.user_answer} — *{verdict}*")
        if lesson.feedback:
            lines.append(f"> {lesson.feedback}")
    return "\n".join(lines)


def _completion_section(state: SessionState) -> str:
    flagged = state.dag.review_ids() if state.dag is not None else []
    if not flagged:
        return "## Session Complete\n\nAll concepts in the learning plan are mastered."
    titles = "\n".join(f"- {state.dag.nodes[nid].title}" for nid in flagged)
    return (
        "## Session Complete\n\n"
        "All concepts in the learning plan were covered. "
        "Still marked for review (not yet mastered):\n\n" + titles
    )
