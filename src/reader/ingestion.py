"""Text download, header stripping, and semantic chunking (configurable per book)."""

import re
from pathlib import Path

import httpx

from src.logger import create_step


DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ── Text acquisition ────────────────────────────────────────────

def download_text(url: str, cache_filename: str) -> str:
    """Download text from URL, caching to data/{cache_filename}."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / cache_filename

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    text = response.text
    cache_path.write_text(text, encoding="utf-8")
    return text


def load_local_file(filepath: str) -> str:
    """Load text from a local file path."""
    path = Path(filepath)
    if not path.is_absolute():
        path = DATA_DIR / path
    return path.read_text(encoding="utf-8")


def acquire_text(source_config: dict) -> str:
    """Acquire text based on source configuration.

    Supports source types: gutenberg, local_file, url.
    """
    source_type = source_config["type"]
    url = source_config.get("url", "")
    cache_filename = source_config.get("cache_filename", "")

    if source_type == "gutenberg":
        return download_text(url, cache_filename)
    elif source_type == "local_file":
        return load_local_file(source_config.get("path", cache_filename))
    elif source_type == "url":
        return download_text(url, cache_filename)
    else:
        raise ValueError(f"Unknown source type: {source_type}")


# ── Text cleaning ───────────────────────────────────────────────

def clean_gutenberg(text: str) -> str:
    """Strip Gutenberg boilerplate markers."""
    start_marker = r"\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .+? \*\*\*"
    end_marker = r"\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .+? \*\*\*"

    start_match = re.search(start_marker, text)
    end_match = re.search(end_marker, text)

    if start_match:
        text = text[start_match.end():]
    if end_match:
        text = text[:end_match.start()]

    return text.strip()


# ── Chunking strategies ─────────────────────────────────────────

def chunk_by_regex(text: str, pattern: str) -> list[dict]:
    """Split text by a regex pattern that captures section identifiers.

    The pattern should have a capture group for the section ID.
    Falls back to single chunk if no matches found.
    """
    splits = list(re.finditer(pattern, text, re.MULTILINE))

    if not splits:
        return [{"part_id": "full_text", "text": text}]

    chunks = []
    for i, match in enumerate(splits):
        part_id = match.group(1).strip()
        start = match.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        chunk_text = text[start:end].strip()
        chunks.append({"part_id": part_id, "text": chunk_text})

    return chunks


def chunk_by_chapter(text: str) -> list[dict]:
    """Split text by chapter headings (Chapter 1, Chapter I, etc.)."""
    return chunk_by_regex(text, r"^(Chapter\s+(?:\d+|[IVXLC]+))[\s.:]*")


def chunk_by_heading(text: str) -> list[dict]:
    """Split text by markdown-style or plain text headings."""
    # Try markdown headings first
    md_chunks = chunk_by_regex(text, r"^(#{1,3}\s+.+)$")
    if len(md_chunks) > 1:
        return md_chunks

    # Fall back to ALL-CAPS headings
    return chunk_by_regex(text, r"^([A-Z][A-Z\s]{3,}[A-Z])$")


def chunk_by_tokens(text: str, max_tokens: int = 2000) -> list[dict]:
    """Split text into approximately equal chunks by word count.

    Tries to split at paragraph boundaries.
    """
    paragraphs = text.split("\n\n")
    chunks = []
    current_text = ""
    current_words = 0
    chunk_idx = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > max_tokens and current_text:
            chunk_idx += 1
            chunks.append({"part_id": f"chunk_{chunk_idx}", "text": current_text.strip()})
            current_text = para
            current_words = para_words
        else:
            current_text = current_text + "\n\n" + para if current_text else para
            current_words += para_words

    if current_text.strip():
        chunk_idx += 1
        chunks.append({"part_id": f"chunk_{chunk_idx}", "text": current_text.strip()})

    return chunks


def dispatch_chunking(text: str, chunking_config: dict) -> list[dict]:
    """Route to the appropriate chunking strategy based on config."""
    strategy = chunking_config.get("strategy", "token")

    if strategy == "regex":
        pattern = chunking_config.get("pattern", "")
        if not pattern:
            raise ValueError("Chunking strategy 'regex' requires a 'pattern' in config")
        return chunk_by_regex(text, pattern)
    elif strategy == "chapter":
        return chunk_by_chapter(text)
    elif strategy == "heading":
        return chunk_by_heading(text)
    elif strategy == "token":
        max_tokens = chunking_config.get("max_tokens", 2000)
        return chunk_by_tokens(text, max_tokens)
    else:
        raise ValueError(f"Unknown chunking strategy: {strategy}")


# ── Pipeline node ────────────────────────────────────────────────

def ingest(state: dict) -> dict:
    """LangGraph node: acquire, clean, and chunk the text based on book config."""
    steps = list(state.get("thinking_log", []))
    book_config = state.get("book_config", {})

    source_config = book_config.get("source", {})
    chunking_config = book_config.get("chunking", {})
    source_type = source_config.get("type", "gutenberg")

    # ── Acquire text ──
    source_desc = source_config.get("url", "") or source_config.get("path", "local file")
    steps.append(create_step(
        layer="reader",
        node="ingestion",
        action="acquire_text",
        input_summary=f"Acquiring text ({source_type}): {source_desc}",
        reasoning=f"Fetching raw text via {source_type} strategy (cached if available)",
    ))

    raw_text = acquire_text(source_config)

    # ── Clean text ──
    if source_type == "gutenberg":
        steps.append(create_step(
            layer="reader",
            node="ingestion",
            action="clean_gutenberg",
            input_summary=f"Raw text length: {len(raw_text)} chars",
            reasoning="Stripping Gutenberg boilerplate to isolate the actual work",
        ))
        cleaned = clean_gutenberg(raw_text)
    else:
        cleaned = raw_text

    # ── Chunk text ──
    strategy = chunking_config.get("strategy", "token")
    steps.append(create_step(
        layer="reader",
        node="ingestion",
        action="chunk_text",
        input_summary=f"Cleaned text length: {len(cleaned)} chars",
        reasoning=f"Splitting text using '{strategy}' strategy",
    ))

    chunks = dispatch_chunking(cleaned, chunking_config)
    raw_chunks = [c["text"] for c in chunks]

    steps.append(create_step(
        layer="reader",
        node="ingestion",
        action="chunking_complete",
        input_summary=f"Produced {len(chunks)} chunks: {[c['part_id'] for c in chunks]}",
        parsed_output={"chunk_count": len(chunks), "part_ids": [c["part_id"] for c in chunks]},
        reasoning=f"Successfully split text into {len(chunks)} parts",
    ))

    return {
        "raw_chunks": raw_chunks,
        "thinking_log": steps,
    }
