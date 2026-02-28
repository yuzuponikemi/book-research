"""Ingestor service package."""
from cogito.services.ingestor.adapters.book import ingest_from_book_config

__all__ = ["ingest_from_book_config"]
