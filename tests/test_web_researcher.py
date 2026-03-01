"""WebResearcher service tests.

Unit tests: schema + planner logic (no LLM / no web).
Integration tests: require Ollama with llama3.2:latest.
  Run with: pytest tests/test_web_researcher.py -m integration -v

Real search tests are skipped unless COGITO_ENABLE_SEARCH=1 is set.
"""

import os
import pytest

from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.web_researcher.planner import Heading
from cogito.services.web_researcher.aggregator import SynthesizedChunk
from cogito.services.web_researcher.searcher import SearchResult


# ── Unit ──────────────────────────────────────────────────────────────────────

class TestWebResearcherUnit:
    def test_heading_dataclass(self) -> None:
        h = Heading(id="cogito", title="Cogito ergo sum", description="Foundation of rationalism")
        assert h.id == "cogito"
        assert h.title == "Cogito ergo sum"

    def test_synthesized_chunk_fields(self) -> None:
        chunk = SynthesizedChunk(
            heading_id="cogito",
            heading_title="Cogito ergo sum",
            summary_text="The Cogito is Descartes' most famous insight.",
            sources=["https://plato.stanford.edu/"],
        )
        assert chunk.heading_id == "cogito"
        assert len(chunk.summary_text) > 10

    def test_web_source_mode_on_concept_graph(
        self, sample_concept_graph_dict: dict
    ) -> None:
        graph = ConceptGraphV1.from_legacy_dict(
            sample_concept_graph_dict,
            subject="Test",
            source_mode="web_researcher",
            generated_by="web_researcher",
        )
        assert graph.source_mode == "web_researcher"
        assert graph.generated_by == "web_researcher"


# ── Integration: LLM (no real web search) ─────────────────────────────────────

@pytest.mark.integration
class TestWebResearcherIntegration:
    def test_plan_headings_from_llm(self, model: str) -> None:
        """LLM infers headings when no book config is given (llama3.2)."""
        from cogito.services.web_researcher.planner import plan_headings

        headings, log = plan_headings(
            subject="Descartes Discourse on the Method",
            author="René Descartes",
            book_config=None,
            model=model,
        )

        assert len(headings) >= 1, "Should produce at least 1 heading"
        for h in headings:
            assert h.id, "Each heading must have an id"
            assert h.title, "Each heading must have a title"
        print(f"\n  → {len(headings)} headings inferred by LLM")
        for h in headings:
            print(f"     [{h.id}] {h.title}")

    def test_aggregate_fake_results(self, model: str) -> None:
        """Aggregator: fake SearchResults → SynthesizedChunk (llama3.2)."""
        from cogito.services.web_researcher.aggregator import aggregate_headings

        heading = Heading(
            id="cogito",
            title="Cogito ergo sum",
            description="Descartes' first principle",
        )
        fake_results = [
            SearchResult(
                query="Descartes cogito ergo sum philosophy",
                title="Cogito ergo sum — Stanford Encyclopedia",
                body=(
                    "The phrase 'I think, therefore I am' is Descartes' first principle. "
                    "It is supposed to be immune to radical doubt. "
                    "From this foundation, Descartes builds his rationalist philosophy."
                ),
                url="https://plato.stanford.edu/entries/descartes/",
            )
        ]

        chunks, log = aggregate_headings(
            headings=[heading],
            results_by_heading={"cogito": fake_results},
            subject="Descartes Discourse on the Method",
            model=model,
        )

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.heading_id == "cogito"
        assert len(chunk.summary_text) > 50, "Summary should be non-trivial"
        print(f"\n  → summary length: {len(chunk.summary_text)} chars")

    def test_synthesize_from_chunks(self, model: str) -> None:
        """Synthesizer: SynthesizedChunks → ConceptGraphV1 (llama3.2)."""
        from cogito.services.web_researcher.synthesizer import synthesize_from_chunks

        fake_chunks = [
            SynthesizedChunk(
                heading_id="cogito",
                heading_title="Cogito ergo sum",
                summary_text=(
                    "The Cogito is Descartes' most famous insight. By doubting everything, "
                    "he found one thing that could not be doubted: the act of doubting itself. "
                    "'I think therefore I am' became the first principle of his philosophy, "
                    "establishing the primacy of mind over matter and laying the groundwork "
                    "for modern rationalism and the subjective turn in philosophy."
                ),
                sources=["https://plato.stanford.edu/entries/descartes/"],
            )
        ]

        graph, log = synthesize_from_chunks(
            chunks=fake_chunks,
            subject="Descartes Discourse on the Method",
            model=model,
        )

        assert isinstance(graph, ConceptGraphV1)
        assert graph.source_mode == "web_researcher"
        assert len(graph.concepts) >= 1
        print(f"\n  → {len(graph.concepts)} concepts, "
              f"{len(graph.aporias)} aporias")


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("COGITO_ENABLE_SEARCH") != "1",
    reason="Set COGITO_ENABLE_SEARCH=1 to run live web search tests",
)
class TestWebResearcherWithRealSearch:
    def test_full_pipeline_with_search(self, model: str) -> None:
        """Full Route B: subject → ConceptGraphV1 with real web search."""
        from cogito.services.web_researcher.planner import plan_headings
        from cogito.services.web_researcher.searcher import search_headings
        from cogito.services.web_researcher.aggregator import aggregate_headings
        from cogito.services.web_researcher.synthesizer import synthesize_from_chunks

        subject = "Descartes Discourse on the Method"
        headings, _ = plan_headings(subject=subject, model=model)
        headings = headings[:2]  # limit for speed

        results_by_heading, _ = search_headings(headings=headings, subject=subject)
        chunks, _ = aggregate_headings(
            headings=headings,
            results_by_heading=results_by_heading,
            subject=subject,
            model=model,
        )
        graph, _ = synthesize_from_chunks(chunks=chunks, subject=subject, model=model)

        assert isinstance(graph, ConceptGraphV1)
        assert len(graph.concepts) >= 2
