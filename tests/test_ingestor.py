"""Ingestor service tests.

These tests do NOT require Ollama — the Ingestor is deterministic text processing.
"""

from pathlib import Path

import pytest

from cogito.schemas.chunks import ChunksV1


# ── Unit: local file ingestion ────────────────────────────────────────────────

class TestIngestorLocalFile:
    def _make_book_config(self, path: Path) -> dict:
        return {
            "book": {"title": "Test Book", "author": "Test Author"},
            "source": {
                "type": "local_file",
                "path": str(path),
            },
            "chunking": {"strategy": "regex", "pattern": r"^(PART\s+[IVX]+)\b"},
        }

    def test_ingest_returns_chunks_v1(self, tmp_text_file: Path) -> None:
        from cogito.services.ingestor.adapters.book import ingest_from_book_config

        book_config = self._make_book_config(tmp_text_file)
        chunks_v1, log = ingest_from_book_config(book_config)

        assert isinstance(chunks_v1, ChunksV1)
        assert len(chunks_v1.chunks) >= 1

    def test_chunks_have_required_fields(self, tmp_text_file: Path) -> None:
        from cogito.services.ingestor.adapters.book import ingest_from_book_config

        book_config = self._make_book_config(tmp_text_file)
        chunks_v1, _ = ingest_from_book_config(book_config)

        for chunk in chunks_v1.chunks:
            assert chunk.id, "Each chunk must have an id"
            assert chunk.text.strip(), "Each chunk must have non-empty text"

    def test_chunks_v1_json_roundtrip(self, tmp_text_file: Path) -> None:
        from cogito.services.ingestor.adapters.book import ingest_from_book_config

        book_config = self._make_book_config(tmp_text_file)
        original, _ = ingest_from_book_config(book_config)

        serialized = original.model_dump_json()
        restored = ChunksV1.model_validate_json(serialized)

        assert len(original.chunks) == len(restored.chunks)
        assert original.subject == restored.subject

    def test_token_chunking_still_produces_chunks(self, tmp_text_file: Path) -> None:
        from cogito.services.ingestor.adapters.book import ingest_from_book_config

        book_config = {
            "book": {"title": "Test", "author": "Author"},
            "source": {"type": "local_file", "path": str(tmp_text_file)},
            "chunking": {"strategy": "token", "max_tokens": 150},
        }
        chunks_v1, _ = ingest_from_book_config(book_config)
        assert len(chunks_v1.chunks) >= 1
