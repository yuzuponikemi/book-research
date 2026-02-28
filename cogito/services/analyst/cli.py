"""Analyst service CLI.

Reads a ChunksV1 JSON file, runs concept extraction + synthesis,
and writes a ConceptGraphV1 JSON file.

Usage:
    python -m cogito.services.analyst \\
        --input  data/run_xxx/01_chunks.json \\
        --output data/run_xxx/03_concept_graph.json \\
        --model  llama3

    # Optionally provide book config for key_terms / work_description:
    python -m cogito.services.analyst \\
        --input  data/run_xxx/01_chunks.json \\
        --output data/run_xxx/03_concept_graph.json \\
        --book   descartes_discourse
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cogito.schemas.chunks import ChunksV1
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.analyst.extractor import extract_all_chunks
from cogito.services.analyst.synthesizer import synthesize_concept_graph


def _load_book_context(book_name: str) -> tuple[str, list[str]]:
    """Load work_description and key_terms from a book config.

    Returns:
        (work_description, key_terms)
    """
    try:
        from src.book_config import load_book_config
        book_config = load_book_config(book_name)
        book = book_config.get("book", {})
        pf = book_config.get("prompt_fragments", {})
        work_description = pf.get(
            "work_description",
            f'{book.get("author", "the author")}\'s "{book.get("title", book_name)}"',
        )
        key_terms = book_config.get("context", {}).get("key_terms", [])
        return work_description, key_terms
    except Exception as e:
        print(f"  Warning: could not load book config '{book_name}': {e}", file=sys.stderr)
        return book_name, []


def run(
    input_path: Path,
    output_path: Path,
    model: str = "llama3",
    book: str | None = None,
) -> ConceptGraphV1:
    """Programmatic entry point (importable from other modules)."""

    # ── Load ChunksV1 ─────────────────────────────────────────────────────────
    print(f"  Loading chunks from {input_path} ...", flush=True)
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    chunks_v1 = ChunksV1.model_validate(raw)

    chunks_tuples = [(c.id, c.text) for c in chunks_v1.chunks]
    subject = chunks_v1.subject

    # ── Resolve work description and key_terms ────────────────────────────────
    if book:
        work_description, key_terms = _load_book_context(book)
    else:
        work_description = subject
        key_terms = []

    # ── Step 1: Extract concepts per chunk ────────────────────────────────────
    print(f"  Extracting concepts from {len(chunks_tuples)} chunks (model: {model}) ...",
          flush=True)
    chunk_analyses, extract_log = extract_all_chunks(
        chunks_tuples, model=model, key_terms=key_terms or None
    )

    # ── Step 2: Synthesize concept graph ──────────────────────────────────────
    print("  Synthesizing concept graph ...", flush=True)
    graph, synth_log = synthesize_concept_graph(
        chunk_analyses,
        work_description=work_description,
        subject=subject,
        model=model,
        source_mode=chunks_v1.source_mode if chunks_v1.source_mode in ("book",) else "book",
    )

    # ── Save output ───────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        graph.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    print(
        f"  ConceptGraphV1 written to {output_path}\n"
        f"  → {len(graph.concepts)} concepts, "
        f"{len(graph.relations)} relations, "
        f"{len(graph.aporias)} aporias",
        flush=True,
    )

    return graph


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Analyst service: ChunksV1 → ConceptGraphV1"
    )
    parser.add_argument(
        "--input", required=True, metavar="PATH",
        help="Path to ChunksV1 JSON file (01_chunks.json)",
    )
    parser.add_argument(
        "--output", required=True, metavar="PATH",
        help="Path to write ConceptGraphV1 JSON file (03_concept_graph.json)",
    )
    parser.add_argument(
        "--model", default="llama3", metavar="MODEL",
        help="Ollama model for extraction + synthesis (default: llama3)",
    )
    parser.add_argument(
        "--book", default=None, metavar="BOOK",
        help="Book config name to load key_terms / work_description (optional)",
    )
    args = parser.parse_args(argv)

    run(
        input_path=Path(args.input),
        output_path=Path(args.output),
        model=args.model,
        book=args.book,
    )


if __name__ == "__main__":
    main()
