"""WebResearcher — Step 4: synthesize SynthesizedChunks → ConceptGraphV1.

Reuses the same synthesis prompt logic as analyst/synthesizer.py,
but sources data from SynthesizedChunks instead of LLM-extracted chunk analyses.
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_ollama import ChatOllama

from cogito.utils.logger import create_step, extract_json
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.web_researcher.aggregator import SynthesizedChunk
# Reuse the same LLM prompt — the output format is identical
from cogito.services.analyst.synthesizer import SYNTHESIS_PROMPT


def synthesize_from_chunks(
    chunks: list[SynthesizedChunk],
    subject: str,
    model: str = "llama3",
) -> tuple[ConceptGraphV1, list[dict]]:
    """Build a ConceptGraphV1 from web-research synthesized chunks.

    The SynthesizedChunks are first converted to the same JSON format that
    the Analyst's extractor would produce, then the same synthesis prompt
    is applied — ensuring the output schema is identical regardless of route.

    Args:
        chunks:  Output of aggregator.aggregate_headings().
        subject: Full subject description.
        model:   Ollama model for synthesis.

    Returns:
        (ConceptGraphV1, thinking_log_entries)
    """
    # Convert SynthesizedChunks into a "pseudo chunk_analyses" format
    # so the SYNTHESIS_PROMPT can operate on them directly.
    pseudo_analyses = [
        {
            "chunk_index": i,
            "heading_id": c.heading_id,
            "heading_title": c.heading_title,
            # The summary_text serves as both the source content and a pre-extracted summary
            "concepts": [],   # will be inferred by the synthesis LLM
            "aporias": [],
            "relations": [],
            "logic_flow": c.summary_text,
            "sources": c.sources,
        }
        for i, c in enumerate(chunks)
    ]

    analyses_json = json.dumps(pseudo_analyses, ensure_ascii=False, indent=2)
    if len(analyses_json) > 30000:
        analyses_json = analyses_json[:30000] + "\n... (truncated)"

    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=num_ctx, format="json")

    prompt = SYNTHESIS_PROMPT.format(
        chunk_count=len(chunks),
        analyses_json=analyses_json,
        work_description=subject,
    )

    raw_response = llm.invoke(prompt).content
    parsed: dict | None = None
    error: str | None = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {
            "concepts": [], "relations": [],
            "aporias": [], "logic_flow": "", "core_frustration": ""
        }

    step = create_step(
        layer="web_researcher", node="synthesizer",
        action="synthesize_concept_graph",
        input_summary=f"Synthesising from {len(chunks)} web-research chunks",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=(
            f"Built graph: {len(parsed.get('concepts', []))} concepts, "
            f"{len(parsed.get('relations', []))} relations, "
            f"{len(parsed.get('aporias', []))} aporias"
        ),
    )

    graph = ConceptGraphV1.from_legacy_dict(
        parsed,
        subject=subject,
        source_mode="web_researcher",
        generated_by="web_researcher",
    )

    return graph, [step]
