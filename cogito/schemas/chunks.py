"""ChunksV1 — output schema of the Ingestor service.

This is the interface contract between Ingestor → Analyst.
Both book-text mode and future adapters (YouTube, web articles) produce this schema.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A single unit of source text, regardless of its origin."""

    id: str = Field(
        description="Unique identifier within this run, e.g. 'PART_IV' or 'web_003'."
    )
    text: str = Field(
        description="The raw text content of this chunk."
    )
    heading: str = Field(
        default="",
        description="Section heading or title for this chunk.",
    )
    source_type: Literal["book_chapter", "web_article", "youtube_transcript", "local_file", "arxiv"] = Field(
        default="book_chapter",
        description="Origin type of this chunk.",
    )
    source_url: str | None = Field(
        default=None,
        description="URL if sourced from the web; None for local/book sources.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary extra metadata (e.g. chapter number, published date).",
    )


class ChunksV1(BaseModel):
    """Root schema for the Ingestor service output (schema version 1)."""

    schema_version: str = Field(default="1.0")
    subject: str = Field(
        description="Human-readable description of the source material, "
                    "e.g. '方法序説 by デカルト'."
    )
    source_mode: Literal["book", "web", "youtube", "local"] = Field(
        description="High-level origin category."
    )
    chunks: list[Chunk] = Field(
        description="Ordered list of text chunks ready for Analyst processing."
    )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def to_raw_chunks(self) -> list[str]:
        """Return plain text list compatible with the legacy CogitoState format."""
        return [c.text for c in self.chunks]

    def chunk_ids(self) -> list[str]:
        return [c.id for c in self.chunks]
