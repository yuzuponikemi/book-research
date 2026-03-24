"""Analyst service tests.

Unit tests: schema verification only (no LLM).
Integration tests: require Ollama with llama3.2:latest.
  Run with: pytest tests/test_analyst.py -m integration -v
"""

import pytest
from langchain_ollama import ChatOllama

from cogito.schemas.concept_graph import ConceptGraphV1


# ── Unit: schema / pure-function tests ────────────────────────────────────────

class TestAnalystUnit:
    def test_concept_graph_from_legacy_dict(
        self, sample_concept_graph_dict: dict
    ) -> None:
        graph = ConceptGraphV1.from_legacy_dict(
            sample_concept_graph_dict,
            subject="Discourse on the Method",
            source_mode="book",
            generated_by="analyst",
        )
        assert graph.source_mode == "book"
        assert graph.generated_by == "analyst"
        assert len(graph.concepts) >= 1
        assert len(graph.aporias) >= 1

    def test_concept_graph_roundtrip(self, sample_concept_graph_dict: dict) -> None:
        graph = ConceptGraphV1.from_legacy_dict(
            sample_concept_graph_dict,
            subject="Test",
            source_mode="book",
            generated_by="analyst",
        )
        restored = ConceptGraphV1.model_validate_json(graph.model_dump_json())
        assert len(graph.concepts) == len(restored.concepts)


# ── Integration: real LLM calls ───────────────────────────────────────────────

@pytest.mark.integration
class TestAnalystIntegration:
    def _make_llm(self, model: str) -> ChatOllama:
        return ChatOllama(model=model, temperature=0.1, num_ctx=8192, format="json")

    def test_extract_single_chunk(self, model: str, sample_text: str) -> None:
        """Single chunk → analysis dict (llama3.2)."""
        from cogito.services.analyst.extractor import extract_chunk

        llm = self._make_llm(model)
        result, step = extract_chunk(
            chunk_text=sample_text[:2000],
            part_id="PART_I",
            llm=llm,
        )

        assert isinstance(result, dict), "extract_chunk must return a dict"
        has_output = bool(
            result.get("concepts") or result.get("aporias") or result.get("logic_flow")
        )
        assert has_output, f"LLM returned no meaningful output: {result}"
        print(f"\n  → concepts: {len(result.get('concepts', []))}, "
              f"aporias: {len(result.get('aporias', []))}")

    def test_extract_all_chunks(self, model: str, sample_text: str) -> None:
        """Multiple chunks → list of analyses (llama3.2)."""
        from cogito.services.analyst.extractor import extract_all_chunks

        chunks = [
            ("PART_I",  sample_text[:800]),
            ("PART_II", sample_text[800:1600]),
        ]
        analyses, log = extract_all_chunks(chunks, model=model)

        assert len(analyses) == 2
        for a in analyses:
            assert isinstance(a, dict)

    def test_synthesize_concept_graph(
        self, model: str, sample_chunk_analysis: dict
    ) -> None:
        """Chunk analyses → ConceptGraphV1 (llama3.2)."""
        from cogito.services.analyst.synthesizer import synthesize_concept_graph

        graph, log = synthesize_concept_graph(
            chunk_analyses=[sample_chunk_analysis],
            work_description="Descartes' Discourse on the Method",
            subject="Discourse on the Method",
            model=model,
        )

        assert isinstance(graph, ConceptGraphV1)
        assert graph.generated_by == "analyst"
        assert graph.source_mode == "book"
        assert len(graph.concepts) >= 1
        print(f"\n  → {len(graph.concepts)} concepts, "
              f"{len(graph.relations)} relations, {len(graph.aporias)} aporias")

    def test_full_analyst_pipeline(self, model: str, sample_text: str) -> None:
        """End-to-end: text chunks → ConceptGraphV1 (llama3.2)."""
        from cogito.services.analyst.extractor import extract_all_chunks
        from cogito.services.analyst.synthesizer import synthesize_concept_graph

        chunks = [("PART_I", sample_text[:1500])]
        analyses, _ = extract_all_chunks(chunks, model=model)
        graph, _ = synthesize_concept_graph(
            chunk_analyses=analyses,
            work_description="Discourse on the Method",
            subject="Discourse on the Method",
            model=model,
        )

        assert isinstance(graph, ConceptGraphV1)
        restored = ConceptGraphV1.model_validate_json(graph.model_dump_json())
        assert restored.subject == graph.subject
