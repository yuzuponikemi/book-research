"""Gutenberg download, header stripping, and semantic chunking."""

import re
from pathlib import Path

import httpx

from src.logger import create_step


DATA_DIR = Path(__file__).parent.parent.parent / "data"
GUTENBERG_URL = "https://gutenberg.org/cache/epub/59/pg59.txt"


def download_text(url: str = GUTENBERG_URL) -> str:
    """Download text from Gutenberg, caching to data/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "pg59.txt"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    text = response.text
    cache_path.write_text(text, encoding="utf-8")
    return text


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


def chunk_by_parts(text: str) -> list[dict]:
    """Split text by PART I through PART VI using Roman numeral detection.

    Returns list of dicts with 'part_id' and 'text' keys.
    """
    # Match "PART I", "PART II", etc. at the start of a line
    pattern = r"^(PART\s+(?:I{1,3}|IV|V|VI))\b"
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


def ingest(state: dict) -> dict:
    """LangGraph node: download, clean, and chunk the text."""
    steps = list(state.get("thinking_log", []))

    steps.append(create_step(
        layer="reader",
        node="ingestion",
        action="download_text",
        input_summary=f"Downloading {GUTENBERG_URL}",
        reasoning="Fetching raw text from Project Gutenberg (cached if available)",
    ))

    raw_text = download_text()

    steps.append(create_step(
        layer="reader",
        node="ingestion",
        action="clean_gutenberg",
        input_summary=f"Raw text length: {len(raw_text)} chars",
        reasoning="Stripping Gutenberg boilerplate to isolate the actual work",
    ))

    cleaned = clean_gutenberg(raw_text)

    steps.append(create_step(
        layer="reader",
        node="ingestion",
        action="chunk_by_parts",
        input_summary=f"Cleaned text length: {len(cleaned)} chars",
        reasoning="Splitting by Roman numeral parts for semantic chunking",
    ))

    chunks = chunk_by_parts(cleaned)
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
