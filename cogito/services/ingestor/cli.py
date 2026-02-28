"""Ingestor CLI.

Usage:
    python -m cogito.services.ingestor \\
        --book descartes_discourse \\
        --output data/run_xxx/01_chunks.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cogito.schemas.chunks import ChunksV1


def run(book: str, output_path: Path) -> ChunksV1:
    from src.book_config import load_book_config
    from cogito.services.ingestor.adapters.book import ingest_from_book_config

    print(f"  Loading book config: {book} ...", flush=True)
    book_config = load_book_config(book)
    print("  Ingesting text ...", flush=True)
    chunks_v1, _log = ingest_from_book_config(book_config)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        chunks_v1.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(
        f"  ChunksV1 written to {output_path}\n"
        f"  → {len(chunks_v1.chunks)} chunks",
        flush=True,
    )
    return chunks_v1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingestor service: book config → ChunksV1"
    )
    parser.add_argument("--book", required=True, metavar="BOOK",
                        help="Book config name from config/books/")
    parser.add_argument("--output", required=True, metavar="PATH",
                        help="Path to write ChunksV1 JSON file (01_chunks.json)")
    args = parser.parse_args(argv)
    run(book=args.book, output_path=Path(args.output))


if __name__ == "__main__":
    main()
