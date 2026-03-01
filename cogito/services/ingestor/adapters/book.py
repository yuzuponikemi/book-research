"""Ingestor adapter for book sources.

Ported and decoupled from src/reader/ingestion.py.
CogitoState dependency removed; returns ChunksV1 directly.
Supports: gutenberg, local_file, url, arxiv.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from cogito.utils.logger import create_step
from cogito.schemas.chunks import Chunk, ChunksV1


DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"


# ── Text acquisition ─────────────────────────────────────────────────────────

def download_text(url: str, cache_filename: str) -> str:
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
    path = Path(filepath)
    if not path.is_absolute():
        path = DATA_DIR / path
    return path.read_text(encoding="utf-8")


def acquire_text(source_config: dict) -> str:
    source_type = source_config["type"]
    url = source_config.get("url", "")
    cache_filename = source_config.get("cache_filename", "")

    if source_type in ("gutenberg", "url"):
        return download_text(url, cache_filename)
    elif source_type == "local_file":
        return load_local_file(source_config.get("path", cache_filename))
    elif source_type == "arxiv":
        from cogito.services.ingestor.adapters.arxiv_client import fetch_arxiv_fulltext
        arxiv_id = source_config["arxiv_id"]
        cache = cache_filename or f"arxiv_{arxiv_id.replace('/', '_')}.md"
        return fetch_arxiv_fulltext(arxiv_id, cache)
    else:
        raise ValueError(f"Unknown source type: {source_type}")


# ── Text cleaning ─────────────────────────────────────────────────────────────

def clean_gutenberg(text: str) -> str:
    start_marker = r"\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .+? \*\*\*"
    end_marker   = r"\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .+? \*\*\*"
    start_match = re.search(start_marker, text)
    end_match   = re.search(end_marker, text)
    if start_match:
        text = text[start_match.end():]
    if end_match:
        text = text[:end_match.start()]
    return text.strip()


# ── Chunking strategies ───────────────────────────────────────────────────────

def chunk_by_regex(text: str, pattern: str) -> list[dict]:
    splits = list(re.finditer(pattern, text, re.MULTILINE))
    if not splits:
        return [{"part_id": "full_text", "text": text}]
    chunks = []
    for i, match in enumerate(splits):
        part_id = match.group(1).strip()
        start = match.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        chunks.append({"part_id": part_id, "text": text[start:end].strip()})
    return chunks


def chunk_by_chapter(text: str) -> list[dict]:
    return chunk_by_regex(text, r"^(Chapter\s+(?:\d+|[IVXLC]+))[\s.:]*")


def chunk_by_heading(text: str) -> list[dict]:
    md_chunks = chunk_by_regex(text, r"^(#{1,3}\s+.+)$")
    if len(md_chunks) > 1:
        return md_chunks
    return chunk_by_regex(text, r"^([A-Z][A-Z\s]{3,}[A-Z])$")


def chunk_by_section(text: str, min_chars: int = 200) -> list[dict]:
    pattern = re.compile(r"^(## .+)$", re.MULTILINE)
    splits = list(pattern.finditer(text))
    if not splits:
        return [{"part_id": "full_text", "text": text}]
    raw_chunks: list[tuple[str, str]] = []
    preamble = text[:splits[0].start()].strip()
    if preamble:
        raw_chunks.append(("preamble", preamble))
    for i, match in enumerate(splits):
        heading = match.group(1).strip()
        start = match.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        part_id = re.sub(r"^#+\s*", "", heading)
        part_id = re.sub(r"[^\w\s-]", "", part_id).strip()[:60]
        raw_chunks.append((part_id, text[start:end].strip()))
    merged: list[dict] = []
    carry_id = ""
    carry_text = ""
    for part_id, chunk_text in raw_chunks:
        if carry_text:
            carry_text = carry_text + "\n\n" + chunk_text
            if len(carry_text) >= min_chars:
                merged.append({"part_id": carry_id, "text": carry_text})
                carry_id = ""
                carry_text = ""
        elif len(chunk_text) < min_chars:
            carry_id = part_id
            carry_text = chunk_text
        else:
            merged.append({"part_id": part_id, "text": chunk_text})
    if carry_text:
        if merged:
            merged[-1]["text"] += "\n\n" + carry_text
        else:
            merged.append({"part_id": carry_id or "full_text", "text": carry_text})
    return merged


def chunk_by_tokens(text: str, max_tokens: int = 2000) -> list[dict]:
    paragraphs = text.split("\n\n")
    chunks: list[dict] = []
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
    elif strategy == "section":
        return chunk_by_section(text, chunking_config.get("min_section_chars", 200))
    elif strategy == "token":
        return chunk_by_tokens(text, chunking_config.get("max_tokens", 2000))
    else:
        raise ValueError(f"Unknown chunking strategy: {strategy}")


# ── Public API ─────────────────────────────────────────────────────────────────

def ingest_from_book_config(book_config: dict) -> tuple[ChunksV1, list[dict]]:
    """Produce a ChunksV1 from a book config dict.

    Args:
        book_config: Loaded from src/book_config.load_book_config().

    Returns:
        (ChunksV1, thinking_log_entries)
    """
    book = book_config.get("book", {})
    source_config = book_config.get("source", {})
    chunking_config = book_config.get("chunking", {})
    source_type = source_config.get("type", "gutenberg")

    subject = (
        book_config.get("prompt_fragments", {}).get("work_description")
        or f'{book.get("author", "Unknown")}: "{book.get("title", "Unknown")}"'
    )

    log: list[dict] = []

    # Acquire
    log.append(create_step(
        layer="ingestor", node="book",
        action="acquire_text",
        input_summary=f"source_type={source_type}",
        reasoning="Fetching raw text",
    ))
    raw_text = acquire_text(source_config)

    # Clean
    if source_type == "gutenberg":
        raw_text = clean_gutenberg(raw_text)

    # Chunk
    raw_chunks = dispatch_chunking(raw_text, chunking_config)

    chunks = [
        Chunk(
            id=c["part_id"],
            text=c["text"],
            heading=c["part_id"],
            source_type="book_chapter",
        )
        for c in raw_chunks
    ]

    log.append(create_step(
        layer="ingestor", node="book",
        action="chunking_complete",
        input_summary=f"Produced {len(chunks)} chunks",
        parsed_output={"part_ids": [c.id for c in chunks]},
        reasoning=f"Split into {len(chunks)} parts",
    ))

    chunks_v1 = ChunksV1(
        subject=subject,
        source_mode="book",
        chunks=chunks,
    )

    return chunks_v1, log
