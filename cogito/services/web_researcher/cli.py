"""WebResearcher service CLI.

Runs the full 4-step pipeline: plan → search → aggregate → synthesize
and writes a ConceptGraphV1 JSON file.

Usage:
    # Using an existing book config (headings defined in config):
    python -m cogito.services.web_researcher \\
        --book   descartes_discourse \\
        --output data/run_xxx/03_concept_graph.json \\
        --model  llama3

    # Using free-form subject + author (headings inferred by LLM):
    python -m cogito.services.web_researcher \\
        --subject "Descartes' Discourse on the Method" \\
        --author  "René Descartes" \\
        --output  data/run_xxx/03_concept_graph.json \\
        --model   llama3
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.web_researcher.planner import plan_headings
from cogito.services.web_researcher.searcher import search_headings
from cogito.services.web_researcher.aggregator import aggregate_headings
from cogito.services.web_researcher.synthesizer import synthesize_from_chunks
from cogito.services.web_researcher.guide_writer import write_book_guide


def run(
    output_path: Path,
    model: str = "llama3",
    guide_model: str = "qwen3-coder-next",
    book: str | None = None,
    subject: str | None = None,
    author: str = "",
    max_results_per_query: int = 4,
    skip_guide: bool = False,
) -> ConceptGraphV1:
    """Programmatic entry point."""

    # ── Resolve subject and book_config ──────────────────────────────────────
    book_config: dict | None = None
    if book:
        from cogito.config.book_config import load_book_config
        book_config = load_book_config(book)
        bk = book_config.get("book", {})
        pf = book_config.get("prompt_fragments", {})
        subject = subject or pf.get(
            "work_description",
            f'{bk.get("author", "")}\'s "{bk.get("title", book)}"',
        )
        author = author or bk.get("author", "")

    if not subject:
        raise ValueError("Either --book or --subject must be provided.")

    print(f"\n{'='*60}")
    print(f"  WebResearcher: {subject}")
    print(f"{'='*60}\n")

    # ── Step 1: Plan headings ─────────────────────────────────────────────────
    print("[1/4] Planning headings ...", flush=True)
    headings, log1 = plan_headings(
        subject=subject, author=author,
        book_config=book_config, model=model,
    )
    print(f"  → {len(headings)} headings: {[h.title for h in headings]}\n")

    # ── Step 2: Search per heading ────────────────────────────────────────────
    print("[2/4] Searching the web ...", flush=True)
    results_by_heading, log2 = search_headings(
        headings, subject=subject, model=model,
        max_results_per_query=max_results_per_query,
    )
    total_results = sum(len(v) for v in results_by_heading.values())
    print(f"\n  → {total_results} total results\n")

    # ── Step 3: Aggregate per heading ─────────────────────────────────────────
    print("[3/4] Aggregating search results ...", flush=True)
    chunks, log3 = aggregate_headings(
        headings, results_by_heading, subject=subject, model=model,
    )
    print(f"\n  → {len(chunks)} synthesized chunks\n")

    # ── Step 4: Synthesize concept graph ──────────────────────────────────────
    print("[4/4] Synthesizing concept graph ...", flush=True)
    graph, log4 = synthesize_from_chunks(chunks, subject=subject, model=model)

    # ── Save raw web search content (truth source for factcheck) ─────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    web_results_path = output_path.parent / "web_search_results.json"
    web_results_data = {
        "subject": subject,
        "chunks": [dataclasses.asdict(c) for c in chunks],
        "raw_results": {
            hid: [dataclasses.asdict(r) for r in results]
            for hid, results in results_by_heading.items()
        },
    }
    web_results_path.write_text(
        json.dumps(web_results_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  → web_search_results.json saved ({web_results_path.stat().st_size:,} bytes)")

    # ── Save concept graph ────────────────────────────────────────────────────
    output_path.write_text(
        graph.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print(f"  ConceptGraphV1 written to {output_path}")
    print(f"  → {len(graph.concepts)} concepts, "
          f"{len(graph.relations)} relations, "
          f"{len(graph.aporias)} aporias")
    print(f"{'='*60}\n")

    # ── Step 5: Generate book guide ───────────────────────────────────────────
    if not skip_guide:
        if not graph.concepts:
            print(
                "[5/5] Skipping book guide — concept graph is empty "
                "(synthesis produced 0 concepts after all retries).",
                flush=True,
            )
        else:
            print("[5/5] Writing book guide ...", flush=True)
            guide_path = output_path.parent / "book_guide.md"
            write_book_guide(
                chunks=chunks,
                headings=headings,
                graph=graph,
                output_path=guide_path,
                book_config=book_config,
                model=guide_model,
            )
            print(f"\n{'='*60}")
            print(f"  Book guide written to {guide_path}")
            print(f"{'='*60}\n")

    return graph


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="WebResearcher service: web search → ConceptGraphV1"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--book", metavar="BOOK",
        help="Book config name from config/books/ (provides subject, author, and headings)",
    )
    source.add_argument(
        "--subject", metavar="SUBJECT",
        help="Free-form subject description (headings will be inferred by LLM)",
    )
    parser.add_argument(
        "--author", default="", metavar="AUTHOR",
        help="Author name (used with --subject for better heading inference)",
    )
    parser.add_argument(
        "--output", required=True, metavar="PATH",
        help="Path to write ConceptGraphV1 JSON file",
    )
    parser.add_argument(
        "--model", default="llama3", metavar="MODEL",
        help="Ollama model for all LLM steps (default: llama3)",
    )
    parser.add_argument(
        "--max-results", type=int, default=4, metavar="N",
        help="Max web results per search query (default: 4)",
    )
    args = parser.parse_args(argv)

    run(
        output_path=Path(args.output),
        model=args.model,
        book=args.book,
        subject=args.subject,
        author=args.author,
        max_results_per_query=args.max_results,
    )


if __name__ == "__main__":
    main()
