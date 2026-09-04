# Session file formats

Shared with the `ai-learner` Python harness (`src/ai_learner/session.py`,
`markdown_log.py`) — keep these shapes exact so either frontend can resume a
session the other started. **Unknown keys are preserved verbatim** at every
level — top-level state, probe/lesson records, the dag and its nodes — and
round-tripped on save, so tools can annotate state without their work being
erased. Prefixing third-party keys with `x_` is recommended (it is what the
matsek spec reserves for extensions), but all unknown keys are preserved
either way. The one extra key this skill itself uses is `search` (below).

## state.json

```json
{
  "schema_version": "1.0",
  "name": "calculus",
  "created_at": "2026-08-23 10:00 UTC",
  "phase": "probe",
  "topic": "Calculus",
  "background": "high-school algebra",
  "ladder": [
    {"id": "limits", "title": "Limits", "description": "one sentence"}
  ],
  "probe_records": [
    {
      "concept_id": "limits",
      "concept_title": "Limits",
      "question": "What is $\\lim_{x\\to 0} x$?",
      "kind": "multiple_choice",
      "choices": ["0", "1", "undefined"],
      "user_answer": "A",
      "correct": true,
      "feedback": "Right: the identity function goes to 0."
    }
  ],
  "boundary_index": null,
  "fact_check_notes": "",
  "dag": {
    "nodes": [
      {"id": "derivatives", "title": "Derivatives", "description": "...",
       "status": "pending", "remedial": false, "needs_review": false},
      {"id": "chain_rule", "title": "Chain rule", "description": "...",
       "status": "pending", "remedial": false, "needs_review": false}
    ],
    "edges": [["derivatives", "chain_rule"]]
  },
  "lessons": [
    {
      "node_id": "derivatives",
      "title": "Derivatives",
      "explanation": "markdown with $...$ LaTeX",
      "svg_path": "assets/001_derivatives.svg",
      "question": "...",
      "kind": "short_answer",
      "choices": [],
      "user_answer": "2x",
      "passed": true,
      "feedback": "Correct.",
      "caution": ""
    }
  ],
  "asset_counter": 1,
  "search": {"low": 0, "high": 5}
}
```

Rules:
- `schema_version`: write `"1.0"` on every save. A file without it is a
  pre-1.0 state: load it normally and stamp the field on the next save.
- `phase` ∈ `setup | probe | plan | teach | done`.
- `name` is the slug of the session directory (lowercase, hyphens).
- Record objects must carry every key shown; use `""`/`null`/`[]` for
  empty, never omit. Keys beyond these are fine and survive a save (see
  above), but nothing may repurpose a known key.
- `dag.edges` entries are `[prerequisite_id, dependent_id]`. **Every id in
  an edge must exist in `dag.nodes`**, and the graph must stay acyclic — the
  harness refuses to load a file that violates either.
- `dag.nodes[].status` ∈ `pending | active | completed | known`.
- A given-up node (learner declined to keep trying) is recorded with
  **`status: "completed"` AND `needs_review: true`** — completed so
  traversal and the completion condition advance past it, flagged so no
  surface ever claims it was mastered. Never leave it pending/active.
- `boundary_index`: index into `ladder` of the first unknown concept; `null`
  until the search converges.
- `asset_counter`: last used asset number — asset files are named
  `assets/NNN_<slug>.svg` with `NNN` zero-padded to 3 digits.
- `search` is this skill's own bookkeeping for the probe binary search
  (harmless to the harness, which reconstructs the search by replay). If
  `phase` is `"probe"` and `search` is missing (session touched or started
  by the harness), reconstruct it the same way before continuing: start
  from `low = 0`, `high = len(ladder) - 1`, then for each graded record in
  `probe_records` in order, find its concept's index `i` in `ladder` and
  apply `correct ? low = i + 1 : high = i - 1`.

## experience.md

Written once into the session directory when the session reaches
`phase: "done"` — the matsek experience bundle the member can later choose
to submit. **Never overwrite an existing `experience.md`**: the member may
have edited it. The harness emits it without `rating`; the skill frontend
asks for one (see SKILL.md) and includes it.

```markdown
---
schema_version: "1.0"
type: experience
tool: tutor
tool_version: "0.1.0"
duration_minutes: 85
rating: 4
consent_public: false
session_ref: "calculus"
---

Free text: what happened, friction, suggested improvements.
```

- `tool` is always `tutor`; `tool_version` is the `ai_learner` package
  version.
- `duration_minutes`: whole minutes from `created_at` to session end; omit
  when not derivable.
- `rating` (1–5) is optional — omit rather than invent.
- `consent_public` starts `false`; only the member flips it.
- `session_ref` is the session slug (`name` in state.json).

## session.md

Re-render the whole file from state on every update (never append-only), in
this section order:

```markdown
# Learning Session: <topic>

- **Session:** `<name>`
- **Started:** <created_at>
- **Phase:** <phase>
- **Background:** <background>

## Knowledge Probe

### Q1. <concept title> — correct|incorrect
<question>

- **A.** <choice> ...

> **Answer:** <user answer>
> <feedback>

**Knowledge boundary:** knows up to *X*; learning starts at *Y*

## Learning Plan

> **Verifier notes:** <fact_check_notes>

```mermaid
<see template below>
```

**Progress:** <completed>/<total> concepts (<k> marked for review)

## Lessons

### 1. <node title>
<explanation, LaTeX intact>

![<title>](assets/001_slug.svg)

**Check:** <question>
- **A.** ... (for multiple choice)

> ⚠️ **Caution:** <only when verification issues remained>

> **Answer:** <answer> — *passed|not yet*
> <feedback>

## Session Complete
<only when phase == done; honest about review-flagged nodes>
```

## Mermaid template

```
graph TD
    node_id["Title"]
    node_id2["Other Title *"]
    node_id --> node_id2
    classDef known fill:#d3f9d8,stroke:#2b8a3e,color:#000;
    classDef completed fill:#a5d8ff,stroke:#1971c2,color:#000;
    classDef active fill:#ffe066,stroke:#e67700,color:#000;
    classDef pending fill:#f1f3f5,stroke:#868e96,color:#000;
    classDef review fill:#ffc9c9,stroke:#c92a2a,color:#000;
    class node_id completed;
    class node_id2 pending;
```

- `*` suffix in the label marks remedial nodes; ` (review)` marks
  `needs_review` nodes, which take `class ... review;` INSTEAD of their
  status class.
- Escape `"` in labels as `#quot;` and replace `[`/`]` with `(`/`)`.
- Node ids are `snake_case` slugs, unique.
