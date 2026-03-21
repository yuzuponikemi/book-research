"""WebResearcher — Step 4: synthesize SynthesizedChunks → ConceptGraphV1.

Reuses the same synthesis prompt logic as analyst/synthesizer.py,
but sources data from SynthesizedChunks instead of LLM-extracted chunk analyses.
"""

from __future__ import annotations

import json
from typing import Literal

import time

from langchain_ollama import ChatOllama

from cogito.utils import event_log

from cogito.utils.logger import create_step, extract_json
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.web_researcher.aggregator import SynthesizedChunk


# Web-researcher-specific synthesis prompt.
# Unlike the analyst path (which receives pre-extracted concepts), here each
# chunk is a summarised web-research section keyed to one explicit heading.
# The prompt guarantees: one concept per heading minimum, then cross-heading
# relations and aporias, matching the ConceptGraphV1 schema.
WEB_SYNTHESIS_PROMPT = """\
You are building a concept graph from web research on the following subject:
{work_description}

The research was structured around {chunk_count} explicit headings. \
Each heading represents a distinct concept area of the book/subject. \
You MUST produce at least one concept per heading — do not merge or drop headings.

--- RESEARCH SECTIONS ---
{analyses_json}
--- END SECTIONS ---

Your tasks:

1. **Extract concepts**: For EACH section/heading, extract 1-2 core concepts. \
   Write the concept name and description in ENGLISH (translate Japanese terms as needed, \
   but keep key Japanese terms in parentheses). \
   Only merge two concepts from DIFFERENT headings if they are absolutely identical — \
   otherwise keep them separate. Aim for {min_concepts}-{max_concepts} total concepts.

2. **Build relations**: For every meaningful conceptual link across headings, \
   add a relation with type "depends_on", "contradicts", or "evolves_into". \
   Aim for at least {min_relations} relations.

3. **Identify aporias**: List 3-6 unresolved tensions or open questions the work raises.

4. **Logic flow**: Write a 6-8 sentence narrative tracing the work's reasoning from \
   first principles to its conclusions.

5. **Core frustration**: One sentence capturing the central unresolved intellectual tension.

Respond ONLY with valid JSON:
{{
  "concepts": [
    {{"id": "slug", "name": "Concept Name", "description": "2-3 sentences.", \
"original_quotes": [], "source_chunk": "heading_id"}}
  ],
  "relations": [
    {{"source": "slug", "target": "slug", \
"relation_type": "depends_on|contradicts|evolves_into", "evidence": "..."}}
  ],
  "aporias": [
    {{"id": "aporia1", "question": "...", "context": "...", "related_concepts": ["slug"]}}
  ],
  "logic_flow": "...",
  "core_frustration": "..."
}}
"""


def synthesize_from_chunks(
    chunks: list[SynthesizedChunk],
    subject: str,
    model: str = "llama3",
) -> tuple[ConceptGraphV1, list[dict]]:
    """Build a ConceptGraphV1 from web-research synthesized chunks.

    Each SynthesizedChunk corresponds to one explicit heading.  The
    web-researcher-specific prompt guarantees at least one concept per heading,
    preventing the over-merging that occurs when the analyst prompt is reused
    with empty pre-extracted concepts.

    Args:
        chunks:  Output of aggregator.aggregate_headings().
        subject: Full subject description.
        model:   Ollama model for synthesis.

    Returns:
        (ConceptGraphV1, thinking_log_entries)
    """
    sections = [
        {
            "chunk_index": i,
            "heading_id": c.heading_id,
            "heading_title": c.heading_title,
            "summary": c.summary_text,
        }
        for i, c in enumerate(chunks)
    ]

    analyses_json = json.dumps(sections, ensure_ascii=False, indent=2)
    if len(analyses_json) > 30000:
        analyses_json = analyses_json[:30000] + "\n... (truncated)"

    min_concepts = len(chunks)          # at least one per heading
    max_concepts = len(chunks) * 2
    min_relations = max(8, len(chunks))

    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=num_ctx, format="json")

    prompt = WEB_SYNTHESIS_PROMPT.format(
        chunk_count=len(chunks),
        analyses_json=analyses_json,
        work_description=subject,
        min_concepts=min_concepts,
        max_concepts=max_concepts,
        min_relations=min_relations,
    )

    _t0 = time.time()
    raw_response = llm.invoke(prompt).content
    event_log.llm("web_researcher/synthesizer", "synthesize_concept_graph", model, time.time() - _t0)
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
