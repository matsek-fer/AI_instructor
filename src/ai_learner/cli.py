"""Command-line interface for the AI-Learner tutor harness.

Commands:
    ai-learner start   [--session NAME] [--vault DIR] [--model ID] [--effort LEVEL]
    ai-learner resume  [--session NAME] [--vault DIR] [--model ID] [--effort LEVEL]
    ai-learner list    [--vault DIR]
    ai-learner status  [--session NAME] [--vault DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config
from .engine import ConsoleIO, TutorEngine
from .errors import TutorError
from .llm import AnthropicLLM
from .session import PHASE_DONE, SessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-learner",
        description="Autonomous AI personal tutor: probe -> plan -> teach, "
        "with a live Markdown/Obsidian session log.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--vault", type=Path, default=None,
                       help="directory holding session folders (default: ./sessions, "
                            "or $AI_LEARNER_VAULT); point it at an Obsidian vault")
        p.add_argument("--session", default=None, help="session name")

    def model_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", default=None, help="Claude model id (default: claude-opus-5)")
        p.add_argument("--effort", default=None,
                       choices=["low", "medium", "high", "xhigh", "max"],
                       help="reasoning effort (default: high)")
        p.add_argument("--no-fallbacks", action="store_true",
                       help="disable server-side refusal fallbacks (beta)")

    p_start = sub.add_parser("start", help="start a new learning session")
    common(p_start)
    model_opts(p_start)

    p_resume = sub.add_parser("resume", help="resume a session (default: most recent)")
    common(p_resume)
    model_opts(p_resume)

    p_list = sub.add_parser("list", help="list sessions in the vault")
    common(p_list)

    p_status = sub.add_parser("status", help="show a session's progress")
    common(p_status)

    return parser


def make_config(args: argparse.Namespace) -> Config:
    config = Config()
    if getattr(args, "vault", None):
        config.vault = args.vault
    if getattr(args, "model", None):
        config.model = args.model
    if getattr(args, "effort", None):
        config.effort = args.effort
    if getattr(args, "no_fallbacks", False):
        config.enable_fallbacks = False
    return config


def cmd_start(args: argparse.Namespace) -> int:
    config = make_config(args)
    store = SessionStore(config.vault)
    state = store.create(args.session)
    return _drive(config, store, state)


def cmd_resume(args: argparse.Namespace) -> int:
    config = make_config(args)
    store = SessionStore(config.vault)
    name = args.session or store.latest()
    if not name:
        print("No sessions to resume. Run `ai-learner start` first.", file=sys.stderr)
        return 1
    state = store.load(name)
    if state.phase == PHASE_DONE:
        print(f"Session {name!r} is already complete: {store.log_path(name)}")
        return 0
    print(f"Resuming session {name!r} (phase: {state.phase}).\n")
    return _drive(config, store, state)


def _drive(config: Config, store: SessionStore, state) -> int:
    llm = AnthropicLLM(config)
    engine = TutorEngine(config, store, state, llm, ConsoleIO())
    try:
        engine.run()
    except (KeyboardInterrupt, EOFError):
        store.save(state)
        print(f"\nPaused. Resume with: ai-learner resume --session {state.name}")
        return 130
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = make_config(args)
    store = SessionStore(config.vault)
    sessions = store.list_sessions()
    if not sessions:
        print(f"No sessions in {config.vault}/")
        return 0
    for name in sessions:
        state = store.load(name)
        topic = state.topic or "(no topic yet)"
        print(f"{name:<32} {state.phase:<8} {topic}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = make_config(args)
    store = SessionStore(config.vault)
    name = args.session or store.latest()
    if not name:
        print("No sessions found.", file=sys.stderr)
        return 1
    state = store.load(name)
    print(f"Session:  {name}")
    print(f"Topic:    {state.topic or '(not set)'}")
    print(f"Phase:    {state.phase}")
    print(f"Probed:   {len(state.probe_records)} questions")
    if state.dag is not None:
        print(f"Plan:     {len(state.dag.completed_ids())}/{len(state.dag)} concepts done")
    print(f"Notes:    {store.log_path(name)}")
    return 0


COMMANDS = {
    "start": cmd_start,
    "resume": cmd_resume,
    "list": cmd_list,
    "status": cmd_status,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except TutorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
