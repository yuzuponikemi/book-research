"""Tests for cogito/schemas/ — the interface contracts between services."""

import json
import pytest
from pathlib import Path

from cogito.schemas.chunks import Chunk, ChunksV1
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.schemas.production import SyllabusV1, ScriptV1


# ── ChunksV1 ──────────────────────────────────────────────────────────────────

class TestChunksV1:
    def test_roundtrip_json(self):
        original = ChunksV1(
            subject="方法序説 by デカルト",
            source_mode="book",
            chunks=[
                Chunk(id="PART_I", text="I was born in France...", heading="PART I",
                      source_type="book_chapter"),
                Chunk(id="PART_IV", text="I think therefore I am...", heading="PART IV",
                      source_type="book_chapter"),
            ],
        )
        serialized = original.model_dump_json()
        restored = ChunksV1.model_validate_json(serialized)
        assert restored.subject == original.subject
        assert len(restored.chunks) == 2
        assert restored.chunks[0].id == "PART_I"

    def test_to_raw_chunks(self):
        cv1 = ChunksV1(
            subject="test", source_mode="book",
            chunks=[
                Chunk(id="c1", text="Hello world"),
                Chunk(id="c2", text="Goodbye world"),
            ],
        )
        raw = cv1.to_raw_chunks()
        assert raw == ["Hello world", "Goodbye world"]

    def test_web_source_type(self):
        chunk = Chunk(
            id="web_001",
            text="Descartes was born...",
            heading="Biography",
            source_type="web_article",
            source_url="https://example.com/descartes",
        )
        assert chunk.source_type == "web_article"
        assert chunk.source_url is not None

    def test_missing_required_field_raises(self):
        with pytest.raises(Exception):
            ChunksV1(source_mode="book", chunks=[])  # subject is required


# ── ConceptGraphV1 ────────────────────────────────────────────────────────────

SAMPLE_LEGACY_DICT = {
    "concepts": [
        {"id": "cogito", "name": "Cogito Ergo Sum", "description": "I think therefore I am",
         "original_quotes": ["I think, therefore I am"], "source_chunk": "PART IV"},
    ],
    "relations": [
        {"source": "methodical_doubt", "target": "cogito",
         "relation_type": "depends_on", "evidence": "Doubt leads to certainty of self"},
    ],
    "aporias": [
        {"id": "mind_body", "question": "How can mind affect body?",
         "context": "Dualism creates interaction problem", "related_concepts": ["cogito"]},
    ],
    "logic_flow": "Starting from doubt, Descartes arrives at certainty of the cogito.",
    "core_frustration": "The impossibility of bridging mind and matter.",
}


class TestConceptGraphV1:
    def test_from_legacy_dict(self):
        graph = ConceptGraphV1.from_legacy_dict(
            SAMPLE_LEGACY_DICT,
            subject="方法序説",
            source_mode="book",
            generated_by="analyst",
        )
        assert graph.schema_version == "1.0"
        assert len(graph.concepts) == 1
        assert graph.concepts[0].id == "cogito"
        assert graph.source_mode == "book"
        assert graph.generated_by == "analyst"

    def test_to_legacy_dict_roundtrip(self):
        graph = ConceptGraphV1.from_legacy_dict(
            SAMPLE_LEGACY_DICT, subject="test", source_mode="book", generated_by="analyst"
        )
        legacy = graph.to_legacy_dict()
        assert "concepts" in legacy
        assert "relations" in legacy
        assert "aporias" in legacy
        assert legacy["concepts"][0]["id"] == "cogito"

    def test_web_researcher_source_mode(self):
        graph = ConceptGraphV1.from_legacy_dict(
            SAMPLE_LEGACY_DICT,
            subject="Descartes via web",
            source_mode="web_researcher",
            generated_by="web_researcher",
        )
        assert graph.source_mode == "web_researcher"
        assert graph.generated_by == "web_researcher"

    def test_json_roundtrip(self):
        graph = ConceptGraphV1.from_legacy_dict(
            SAMPLE_LEGACY_DICT, subject="test", source_mode="book", generated_by="analyst"
        )
        restored = ConceptGraphV1.model_validate_json(graph.model_dump_json())
        assert restored.subject == graph.subject
        assert restored.concept_ids() == graph.concept_ids()

    def test_load_existing_run_file(self):
        """Verify existing pipeline output can be loaded as ConceptGraphV1."""
        data_dir = Path(__file__).parent.parent / "data"
        # Find any existing concept_graph.json
        existing = list(data_dir.glob("*/03_concept_graph.json"))
        if not existing:
            pytest.skip("No existing 03_concept_graph.json found in data/")
        raw = json.loads(existing[0].read_text())
        # Should succeed (backward compatibility)
        graph = ConceptGraphV1.from_legacy_dict(
            raw, subject="existing run", source_mode="book", generated_by="analyst"
        )
        assert len(graph.concepts) > 0


# ── SyllabusV1 ────────────────────────────────────────────────────────────────

class TestSyllabusV1:
    def test_from_legacy_dict(self):
        legacy = {
            "mode": "essence",
            "episodes": [
                {
                    "episode_number": 1,
                    "title": "The Doubt That Shook the World",
                    "theme": "Methodological scepticism",
                    "concept_ids": ["methodical_doubt"],
                    "aporia_ids": [],
                    "cliffhanger": "Can we know anything at all?",
                    "cognitive_bridge": "Like deleting all your files and starting fresh",
                },
            ],
            "meta_narrative": "How one man rebuilt knowledge from scratch.",
        }
        syllabus = SyllabusV1.from_legacy_dict(legacy, subject="方法序説")
        assert syllabus.mode == "essence"
        assert len(syllabus.episodes) == 1
        assert syllabus.episodes[0].episode_number == 1
