# AI-Learner

An autonomous AI personal tutor, implemented from
[`AI_Learner_System_Spec.md`](AI_Learner_System_Spec.md): a strict
**Probe → Plan → Teach** loop that mirrors the whole session into a
live-updating Markdown note (Obsidian-compatible: LaTeX, inline Mermaid,
embedded SVG).

It ships as **two interchangeable frontends** over the same session files:

| Frontend | Run it | Billing | Character |
|---|---|---|---|
| **Claude Code skill** (`/tutor`) | `claude` in this repo, then `/tutor` | Your Claude subscription | Conversational: interrupt any time, ask about the graph, take detours |
| **Python harness** (`ai-learner`) | `ai-learner start` | Anthropic API (per token) | Deterministic: binary search, DAG validation, and pacing enforced in code |

Both write `sessions/<name>/` (`state.json`, `session.md`, `assets/`), so a
session started in one can be resumed in the other.

## Frontend 1: the `/tutor` skill (Claude Code)

```bash
cd this-repo
claude          # your normal Claude Code session
> /tutor
```

Keep `sessions/<name>/session.md` open in Obsidian (or a Markdown preview
with Mermaid support) in a second window — that's the rendered UI: the
learning-plan graph, LaTeX, and diagrams update live while the conversation
runs in the terminal. Ask free-form questions mid-lesson ("why does node 3
depend on 2?"); the protocol pauses, answers, and resumes.

The skill lives in [`.claude/skills/tutor/`](.claude/skills/tutor/SKILL.md).
To use it outside this repo, copy that folder to `~/.claude/skills/tutor/`.
Diagrams are visually self-inspected: the skill renders each SVG to PNG
(`librsvg`/`inkscape`/`imagemagick` — install one) and looks at the result
before embedding it.

## Frontend 2: the Python harness

### How the harness works

```
+-----------------------------------------------------------------+
|                 session.md (Obsidian / MD viewer)               |
|          live LaTeX + Mermaid DAG + embedded SVG assets         |
+-----------------------------------------------------------------+
                              ^ re-rendered after every state change
+-----------------------------------------------------------------+
|                    TutorEngine (engine.py)                      |
|         state machine: setup -> probe -> plan -> teach          |
+-----------------------------------------------------------------+
     |                        |                        |
     v                        v                        v
 ProbeModule             Planner + DAG            Sub-agents
 binary search        Mermaid dependency        FactChecker
 over prerequisite    graph, acyclicity         SVGAgent (generate ->
 ladder               enforced in code          inspect -> self-correct)
```

- **Probe** — the model generates a prerequisite ladder and diagnostic
  questions; a *deterministic binary search in the harness* decides what to
  ask next and pinpoints the exact boundary between known and unknown in
  O(log n) questions.
- **Plan** — a fact-checking sub-agent verifies the concepts, then the planner
  produces a dependency DAG. The harness validates acyclicity structurally
  (an invalid plan is bounced back to the model with the exact error) and
  renders it as a Mermaid diagram in the note.
- **Teach** — one atomic reasoning step per DAG node. Every step is verified
  by the fact-check sub-agent before the learner sees it, every step ends in
  a mandatory assessment, and a failed assessment triggers dynamic
  recalibration: re-teach from a different angle, or splice remedial
  sub-nodes into the DAG. Visuals are produced by an SVG sub-agent that
  generates, statically validates, self-inspects, and corrects its own output
  before the diagram is embedded.

### Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Authentication: set `ANTHROPIC_API_KEY`, or log in once with `ant auth login`
(the SDK picks up the profile automatically).

### Use

```bash
ai-learner start                      # begins with the Phase-1 probing question
ai-learner resume                     # continue the most recent session
ai-learner list
ai-learner status --session NAME
```

Options: `--vault DIR` (where session folders live — point it inside an
Obsidian vault to watch the note render live), `--model ID`, `--effort
low|medium|high|xhigh|max`, `--no-fallbacks`.

Environment variables: `AI_LEARNER_VAULT`, `AI_LEARNER_MODEL`,
`AI_LEARNER_EFFORT`.

Each session directory contains:

```
sessions/<name>/
├── state.json     # resumable session state
├── session.md     # the live note
└── assets/        # generated SVG diagrams
```

`Ctrl-C` at any point saves state; `ai-learner resume` continues exactly where
the session stopped (including mid-binary-search).

### Model configuration

- Model: `claude-opus-5` by default. Thinking is adaptive (on by default for
  this model); depth is controlled with `--effort` (default `high`).
- All model outputs use structured outputs (`output_config.format` with JSON
  schemas), so questions, plans, grades, and SVGs arrive schema-valid.
- Server-side refusal fallbacks (beta) are enabled by default: if a safety
  classifier declines a request, the API transparently re-serves it on
  Anthropic's recommended fallback model instead of failing the lesson.
  Disable with `--no-fallbacks`.

## Development

```bash
pytest
```

The suite covers the DAG invariants, the binary search, the Markdown renderer,
the SVG static inspector, persistence/resume, and a fully scripted end-to-end
session — no network or API key needed (the model is faked).
