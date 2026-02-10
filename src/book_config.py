"""Book configuration loader with validation and template resolution."""

from pathlib import Path

import yaml


BOOKS_DIR = Path(__file__).parent.parent / "config" / "books"
PROJECT_ROOT = Path(__file__).parent.parent


def load_book_config(book_name: str) -> dict:
    """Load a book config YAML, validate required fields, resolve templates.

    Args:
        book_name: Name of the book config file (without .yaml extension).
                   e.g. "descartes_discourse" loads config/books/descartes_discourse.yaml

    Returns:
        Fully resolved book configuration dict.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If required fields are missing.
    """
    config_path = BOOKS_DIR / f"{book_name}.yaml"
    if not config_path.exists():
        available = [p.stem for p in BOOKS_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"Book config '{book_name}' not found at {config_path}\n"
            f"Available: {', '.join(available) or '(none)'}"
        )

    with open(config_path) as f:
        config = yaml.safe_load(f)

    _validate(config, book_name)
    _apply_defaults(config)
    _resolve_templates(config)
    _resolve_paths(config)
    return config


def _validate(config: dict, book_name: str) -> None:
    """Ensure required top-level keys and fields exist."""
    required_sections = ["book", "source", "chunking"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Book config '{book_name}' missing required section: '{section}'")

    book = config["book"]
    for field in ("title", "author"):
        if field not in book:
            raise ValueError(f"Book config '{book_name}' missing book.{field}")

    source = config["source"]
    for field in ("type",):
        if field not in source:
            raise ValueError(f"Book config '{book_name}' missing source.{field}")

    chunking = config["chunking"]
    if "strategy" not in chunking:
        raise ValueError(f"Book config '{book_name}' missing chunking.strategy")


def _apply_defaults(config: dict) -> None:
    """Fill in optional fields with sensible defaults."""
    book = config["book"]
    book.setdefault("title_ja", book["title"])
    book.setdefault("author_ja", book["author"])
    book.setdefault("year", "")

    source = config["source"]
    source.setdefault("url", "")
    source.setdefault("cache_filename", "")

    chunking = config["chunking"]
    chunking.setdefault("pattern", "")

    config.setdefault("research", {})
    research = config["research"]
    research.setdefault("search_queries", [])
    research.setdefault("reference_files", [])
    research.setdefault("max_search_results", 5)

    config.setdefault("context", {})
    ctx = config["context"]
    ctx.setdefault("era", "")
    ctx.setdefault("tradition", "")
    ctx.setdefault("key_terms", [])
    ctx.setdefault("notable_critics", [])

    config.setdefault("prompt_fragments", {})
    pf = config["prompt_fragments"]
    pf.setdefault("work_description", f'{book["author"]}\'s "{book["title"]}"')
    pf.setdefault("analysis_guidance", "")


def _resolve_templates(config: dict) -> None:
    """Replace {author}, {title} etc. in search_queries and prompt_fragments."""
    book = config["book"]
    template_vars = {
        "author": book["author"],
        "title": book["title"],
        "author_ja": book["author_ja"],
        "title_ja": book["title_ja"],
        "year": str(book.get("year", "")),
    }

    # Resolve search queries
    queries = config["research"].get("search_queries", [])
    config["research"]["search_queries"] = [
        q.format(**template_vars) for q in queries
    ]

    # Resolve prompt fragments
    pf = config["prompt_fragments"]
    for key, value in pf.items():
        if isinstance(value, str):
            pf[key] = value.format(**template_vars)


def _resolve_paths(config: dict) -> None:
    """Resolve relative paths in reference_files to absolute paths."""
    ref_files = config["research"].get("reference_files", [])
    resolved = []
    for ref in ref_files:
        path = Path(ref)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        resolved.append(str(path))
    config["research"]["reference_files"] = resolved
