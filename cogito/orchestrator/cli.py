"""Orchestrator CLI — the unified entry point replacing main.py.

This is a thin wrapper that wires the cogito services together using
file-based interfaces (JSON files), mirroring the existing main.py behaviour
but composed from independent services.

Usage:
    # Route A: book text → podcast (equivalent to main.py default)
    python -m cogito.orchestrator \\
        --book descartes_discourse --mode essence --persona descartes_default

    # Route B: web research → podcast (NEW)
    python -m cogito.orchestrator \\
        --book descartes_discourse --source web --mode essence

    # Route B with free-form subject:
    python -m cogito.orchestrator \\
        --subject "ニーチェ ツァラトゥストラはこう言った" \\
        --source web --mode curriculum

    # Resume from existing concept graph:
    python -m cogito.orchestrator \\
        --from-graph data/run_xxx/03_concept_graph.json \\
        --mode essence --persona socratic

Flags:
    --source      book | web           (default: book)
    --book        Book config name     (config/books/)
    --subject     Free-form subject    (for web mode without a book config)
    --mode        essence | curriculum | topic
    --topic       Topic for topic mode
    --persona     Persona preset name
    --from-graph  Skip ingestion/analysis, start from an existing concept graph
    --output-dir  Where to save run outputs (default: data/run_YYYYMMDD_HHMMSS)
    --reader-model     Ollama model for analysis / planning
    --dramaturg-model  Ollama model for script writing
    --skip-audio       Skip VOICEVOX audio synthesis
    --skip-translate   Skip Japanese translation
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Literal

import yaml

from cogito.schemas.concept_graph import ConceptGraphV1


DATA_DIR  = Path(__file__).parent.parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _make_run_id() -> str:
    from datetime import datetime
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


def _save_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Route A helpers ────────────────────────────────────────────────────────────

def _run_route_a(args: argparse.Namespace, run_dir: Path) -> ConceptGraphV1:
    """Ingestor → Analyst → ConceptGraphV1."""
    from cogito.services.ingestor.adapters.book import ingest_from_book_config
    from cogito.services.analyst.extractor import extract_all_chunks
    from cogito.services.analyst.synthesizer import synthesize_concept_graph
    from src.book_config import load_book_config

    book_config = load_book_config(args.book)
    bk = book_config.get("book", {})
    pf = book_config.get("prompt_fragments", {})
    work_description = pf.get(
        "work_description",
        f'{bk.get("author", "")}\'s "{bk.get("title", args.book)}"',
    )
    key_terms = book_config.get("context", {}).get("key_terms", [])
    subject = work_description

    print("[1/3] Ingesting text ...", flush=True)
    chunks_v1, _log = ingest_from_book_config(book_config)
    _save_json(run_dir / "01_chunks.json", chunks_v1.model_dump())
    print(f"  → {len(chunks_v1.chunks)} chunks\n", flush=True)

    print("[2/3] Extracting concepts ...", flush=True)
    chunk_tuples = [(c.id, c.text) for c in chunks_v1.chunks]
    analyses, _log2 = extract_all_chunks(
        chunk_tuples, model=args.reader_model, key_terms=key_terms or None
    )
    _save_json(run_dir / "02_chunk_analyses.json", analyses)
    print(flush=True)

    print("[3/3] Synthesising concept graph ...", flush=True)
    graph, _log3 = synthesize_concept_graph(
        analyses, work_description=work_description, subject=subject, model=args.reader_model
    )
    return graph


# ── Route B helper ─────────────────────────────────────────────────────────────

def _run_route_b(args: argparse.Namespace, run_dir: Path) -> ConceptGraphV1:
    """WebResearcher → ConceptGraphV1."""
    from cogito.services.web_researcher.cli import run as wr_run

    subject = getattr(args, "subject", None)
    author = ""
    book_config = None

    if args.book:
        from src.book_config import load_book_config
        book_config_data = load_book_config(args.book)
        bk = book_config_data.get("book", {})
        pf = book_config_data.get("prompt_fragments", {})
        subject = subject or pf.get(
            "work_description",
            f'{bk.get("author", "")}\'s "{bk.get("title", args.book)}"',
        )
        author = bk.get("author", "")

    graph = wr_run(
        output_path=run_dir / "03_concept_graph.json",
        model=args.reader_model,
        book=args.book,
        subject=subject,
        author=author,
    )
    return graph


# ── Main ───────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    run_id = _make_run_id()
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    source = args.source

    _banner(run_id, source, args)

    # ── Concept graph ──────────────────────────────────────────────────────────
    if args.from_graph:
        print(f"[SKIP] Loading existing concept graph from {args.from_graph} ...", flush=True)
        raw = json.loads(Path(args.from_graph).read_text(encoding="utf-8"))
        if "schema_version" in raw and "source_mode" in raw:
            graph = ConceptGraphV1.model_validate(raw)
        else:
            graph = ConceptGraphV1.from_legacy_dict(
                raw, subject=raw.get("subject", "unknown"),
                source_mode="book", generated_by="analyst"
            )
    elif source == "web":
        graph = _run_route_b(args, run_dir)
    else:
        graph = _run_route_a(args, run_dir)

    # Save canonical graph
    cg_path = run_dir / "03_concept_graph.json"
    cg_path.write_text(graph.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    print(f"\n  ConceptGraph: {len(graph.concepts)} concepts, "
          f"{len(graph.relations)} relations, {len(graph.aporias)} aporias\n", flush=True)

    # ── Producer ───────────────────────────────────────────────────────────────
    from cogito.services.producer.cli import run as producer_run

    book_meta = args.book
    print("Producing podcast scripts ...", flush=True)
    syllabus, scripts = producer_run(
        input_path=cg_path,
        output_dir=run_dir,
        fmt="podcast",
        mode=args.mode,
        topic=args.topic,
        persona_preset=args.persona,
        planner_model=args.reader_model,
        dramaturg_model=args.dramaturg_model,
        book=book_meta,
    )

    # ── Optional: translation ──────────────────────────────────────────────────
    if not args.skip_translate:
        print("\nTranslating intermediate outputs ...", flush=True)
        from src.translator import translate_intermediate_outputs
        translate_intermediate_outputs(
            run_dir, model=args.translator_model,
            work_description=graph.subject,
        )

    # ── Optional: audio ────────────────────────────────────────────────────────
    if not args.skip_audio:
        print("\nAudio synthesis is handled via the legacy pipeline.", flush=True)
        print(f"  Run: python main.py --resume {run_id} --from-node synthesize_audio",
              flush=True)

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Done!")
    print("=" * 60)
    print(f"  Output : {run_dir}/")
    print(f"  Resume : python main.py --resume {run_id} --from-node synthesize_audio")
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
    parser.add_argument("--skip-translate", action="store_true")
    parser.add_argument("--skip-audio", action="store_true")

    args = parser.parse_args(argv)

    if args.source == "web" and not args.book and not args.subject:
        parser.error("--source web requires either --book or --subject")
    if args.source == "book" and not args.book and not args.from_graph:
        parser.error("--source book requires --book (or use --from-graph)")
    if args.mode == "topic" and not args.topic:
        parser.error("--topic is required when mode=topic")

    run(args)


if __name__ == "__main__":
    main()
