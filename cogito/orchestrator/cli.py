"""Orchestrator CLI — the unified entry point replacing main.py.

Wires the cogito services together via LangGraph (with SQLite checkpointing),
mirroring the original main.py behaviour but composed from independent services.

Usage:
    # Route A: book text → podcast (default)
    python -m cogito.orchestrator \\
        --book descartes_discourse --mode essence --persona descartes_default

    # Route B: web research → podcast
    python -m cogito.orchestrator \\
        --book descartes_discourse --source web --mode essence

    # Free-form subject (no book config):
    python -m cogito.orchestrator \\
        --subject "ニーチェ ツァラトゥストラはこう言った" \\
        --source web --mode curriculum

    # Resume from existing concept graph:
    python -m cogito.orchestrator \\
        --from-graph data/run_xxx/03_concept_graph.json \\
        --mode essence --persona socratic

    # Resume an interrupted run:
    python -m cogito.orchestrator \\
        --resume run_20260101_120000

Flags:
    --source      book | web           (default: book)
    --book        Book config name     (config/books/)
    --subject     Free-form subject    (for web mode without a book config)
    --mode        essence | curriculum | topic
    --topic       Topic for topic mode
    --persona     Persona preset name
    --from-graph  Skip ingestion/analysis, start from an existing concept graph
    --resume      Resume a previously interrupted run by run_id
    --from-node   When resuming, jump to a specific node name
    --reader-model     Ollama model for analysis / planning
    --dramaturg-model  Ollama model for script writing
    --skip-research    Skip web research stage
    --skip-audio       Skip VOICEVOX audio synthesis
    --skip-translate   Skip Japanese translation
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from langgraph.checkpoint.sqlite import SqliteSaver

from cogito.orchestrator.graph import build_graph
from cogito.orchestrator.state import CogitoState
from cogito.schemas.concept_graph import ConceptGraphV1


DATA_DIR   = Path(__file__).parent.parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CHECKPOINTS_DB = DATA_DIR / "checkpoints.db"

THREAD_ID = "cogito"


def _make_run_id() -> str:
    return datetime.now().strftime("run_%Y%m%d_%H%M%S")


def _banner(run_id: str, source: str, args: argparse.Namespace) -> None:
    print("=" * 60)
    print("  Project Cogito  (cogito orchestrator)")
    print("=" * 60)
    print(f"  Run ID     : {run_id}")
    print(f"  Source     : {source}")
    if args.book:
        print(f"  Book       : {args.book}")
    if getattr(args, "subject", None):
        print(f"  Subject    : {args.subject}")
    print(f"  Mode       : {args.mode}")
    print(f"  Persona    : {args.persona}")
    print(f"  Reader     : {args.reader_model}")
    print(f"  Dramaturg  : {args.dramaturg_model}")
    print("=" * 60)
    print()


def _load_persona_config(preset_name: str) -> dict:
    """Load persona config dict from personas.yaml, injecting _preset key."""
    personas_path = CONFIG_DIR / "personas.yaml"
    with open(personas_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    presets = config.get("presets", {})
    if preset_name not in presets:
        available = ", ".join(presets.keys())
        raise ValueError(f"Unknown persona preset '{preset_name}'. Available: {available}")
    data = dict(presets[preset_name])
    data["_preset"] = preset_name
    return data


def _build_initial_state(args: argparse.Namespace, run_id: str) -> CogitoState:
    """Construct the initial LangGraph state from CLI args."""
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    persona_config = _load_persona_config(args.persona)

    # Resolve book config and work_description
    book_config: dict = {}
    work_description = getattr(args, "subject", None) or ""

    if args.book:
        from cogito.config.book_config import load_book_config
        book_config = load_book_config(args.book)
        book_config["_name"] = args.book
        bk = book_config.get("book", {})
        pf = book_config.get("prompt_fragments", {})
        work_description = work_description or pf.get(
            "work_description",
            f'{bk.get("author", "")}\'s "{bk.get("title", args.book)}"',
        )

    source = args.source
    skip_research = args.skip_research or (source == "book")

    state: CogitoState = {
        "book_config": book_config,
        "book_title": book_config.get("book", {}).get("title", work_description),
        "mode": args.mode,
        "topic": args.topic,
        "persona_config": persona_config,
        "reader_model": args.reader_model,
        "dramaturg_model": args.dramaturg_model,
        "translator_model": args.translator_model,
        "work_description": work_description,
        "run_dir": str(run_dir),
        "run_id": run_id,
        "skip_research": skip_research,
        "skip_audio": args.skip_audio,
        "skip_translate": args.skip_translate,
        "chunk_tuples": [],
        "chunk_analyses": [],
        "concept_graph_path": "",
        "scripts": [],
        "audio_metadata": [],
        "thinking_log": [],
    }
    return state


def run(args: argparse.Namespace) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS_DB.parent.mkdir(parents=True, exist_ok=True)

    # ── Resume an existing run ─────────────────────────────────────────────────
    if args.resume:
        run_id = args.resume
        print(f"[RESUME] Resuming run {run_id} ...", flush=True)
    else:
        run_id = _make_run_id()

    _banner(run_id, args.source, args)

    # ── Build graph with SQLite checkpointing ──────────────────────────────────
    conn = sqlite3.connect(str(CHECKPOINTS_DB))
    checkpointer = SqliteSaver(conn)
    graph = build_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": run_id}}

    # ── Handle --from-graph shortcut ───────────────────────────────────────────
    if args.from_graph:
        print(f"[SKIP] Loading concept graph from {args.from_graph} ...", flush=True)
        raw = json.loads(Path(args.from_graph).read_text(encoding="utf-8"))
        if "schema_version" in raw and "source_mode" in raw:
            graph_obj = ConceptGraphV1.model_validate(raw)
        else:
            graph_obj = ConceptGraphV1.from_legacy_dict(
                raw, subject=raw.get("subject", "unknown"),
                source_mode="book", generated_by="analyst"
            )

        run_dir = DATA_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        cg_path = run_dir / "03_concept_graph.json"
        cg_path.write_text(graph_obj.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

        # Bootstrap state and jump straight to produce
        initial = _build_initial_state(args, run_id)
        initial["concept_graph_path"] = str(cg_path)

        # Inject state into checkpointer so graph can resume from 'produce'
        from cogito.services.producer.cli import run as producer_run
        producer_run(
            input_path=cg_path,
            output_dir=run_dir,
            fmt="podcast",
            mode=args.mode,
            topic=args.topic,
            persona_preset=args.persona,
            planner_model=args.reader_model,
            dramaturg_model=args.dramaturg_model,
            book=args.book,
        )
        _print_summary(run_id, DATA_DIR / run_id)
        return

    # ── Normal run or resume via LangGraph ────────────────────────────────────
    if not args.resume:
        initial_state = _build_initial_state(args, run_id)
        result = graph.invoke(initial_state, config=config)
    else:
        # Resume: supply no input — LangGraph reloads from checkpoint
        result = graph.invoke(None, config=config)

    _print_summary(run_id, DATA_DIR / run_id)


def _print_summary(run_id: str, run_dir: Path) -> None:
    print()
    print("=" * 60)
    print("  Done!")
    print("=" * 60)
    print(f"  Output : {run_dir}/")
    print(f"  Run ID : {run_id}")
    print()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Project Cogito orchestrator — unified entry point"
    )
    # Source
    src_grp = parser.add_mutually_exclusive_group()
    src_grp.add_argument("--book", default=None, metavar="BOOK",
                         help="Book config name (Route A default or Route B with config)")
    src_grp.add_argument("--subject", default=None, metavar="SUBJECT",
                         help="Free-form subject for Route B (web mode only)")
    src_grp.add_argument("--from-graph", default=None, metavar="PATH",
                         help="Skip ingestion, use existing ConceptGraphV1 JSON")
    parser.add_argument("--source", default="book", choices=["book", "web"],
                        help="Input source mode (default: book)")
    parser.add_argument("--resume", default=None, metavar="RUN_ID",
                        help="Resume a previously interrupted run by its run_id")
    # Producer
    parser.add_argument("--mode", default="essence",
                        choices=["essence", "curriculum", "topic"])
    parser.add_argument("--topic", default=None)
    parser.add_argument("--persona", default="descartes_default")
    # Models
    parser.add_argument("--reader-model", default="llama3")
    parser.add_argument("--dramaturg-model", default="qwen3-next")
    parser.add_argument("--translator-model", default="translategemma:12b")
    # Flags
    parser.add_argument("--skip-research", action="store_true")
    parser.add_argument("--skip-translate", action="store_true")
    parser.add_argument("--skip-audio", action="store_true")

    args = parser.parse_args(argv)

    if not args.resume:
        if args.source == "web" and not args.book and not args.subject:
            parser.error("--source web requires either --book or --subject")
        if args.source == "book" and not args.book and not args.from_graph:
            parser.error("--source book requires --book (or use --from-graph)")
        if args.mode == "topic" and not args.topic:
            parser.error("--topic is required when mode=topic")

    run(args)


if __name__ == "__main__":
    main()
