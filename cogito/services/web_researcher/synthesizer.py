"""WebResearcher — Step 4: synthesize SynthesizedChunks → ConceptGraphV1.

Reuses the same synthesis prompt logic as analyst/synthesizer.py,
but sources data from SynthesizedChunks instead of LLM-extracted chunk analyses.
"""

from __future__ import annotations

import json
import time

from langchain_ollama import ChatOllama

from cogito.utils import event_log

from cogito.utils.logger import create_step, extract_json
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.web_researcher.aggregator import SynthesizedChunk

# Maximum number of synthesis attempts before giving up and returning partial results.
_MAX_SYNTHESIS_RETRIES = 3

# Normalise relation_type values that LLMs sometimes invent.
# Mirrors the same map in analyst/synthesizer.py.
_RELATION_MAP: dict[str, str] = {
    "necessitates": "depends_on",
    "is_prerequisite_for": "depends_on",
    "requires": "depends_on",
    "leads_to": "depends_on",
    "enables": "depends_on",
    "is_represented_by": "depends_on",
    "justifies": "depends_on",
    "supports": "depends_on",
    "is_attacked_by": "contradicts",
    "opposes": "contradicts",
    "conflicts_with": "contradicts",
    "negates": "contradicts",
    "rejects": "contradicts",
    "challenges": "contradicts",
    "transforms_into": "evolves_into",
    "becomes": "evolves_into",
    "develops_into": "evolves_into",
    # Generic placeholder the LLM sometimes emits
    "relation_type_placeholder": "depends_on",
}
_VALID_RELATION_TYPES = {"depends_on", "contradicts", "evolves_into"}


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


def _normalise_relations(parsed: dict) -> None:
    """In-place: map non-canonical relation_type values to valid ones."""
    for rel in parsed.get("relations", []):
        rt = rel.get("relation_type", "")
        if rt not in _VALID_RELATION_TYPES:
            rel["relation_type"] = _RELATION_MAP.get(rt, "depends_on")


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

    Retry logic:
    - Up to _MAX_SYNTHESIS_RETRIES attempts with increasing temperature.
    - A result is considered valid if it contains at least one concept.
    - If all retries are exhausted, partial (possibly empty) results are
      returned so the pipeline can continue rather than hanging.

    Args:
        chunks:  Output of aggregator.aggregate_headings().
        subject: Full subject description.
        model:   Ollama model for synthesis.

    Returns:
        (ConceptGraphV1, thinking_log_entries)
    """
    if not chunks:
        print("  ⚠️  synthesize_from_chunks: 0 chunks — returning empty graph", flush=True)
        empty = ConceptGraphV1(
            subject=subject, source_mode="web_researcher", generated_by="web_researcher",
            concepts=[], relations=[], aporias=[], logic_flow="", core_frustration=""
        )
        return empty, []

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

    prompt = WEB_SYNTHESIS_PROMPT.format(
        chunk_count=len(chunks),
        analyses_json=analyses_json,
        work_description=subject,
        min_concepts=min_concepts,
        max_concepts=max_concepts,
        min_relations=min_relations,
    )

    all_steps: list[dict] = []
    parsed: dict = {
        "concepts": [], "relations": [],
        "aporias": [], "logic_flow": "", "core_frustration": ""
    }
    last_error: str | None = None

    for attempt in range(1, _MAX_SYNTHESIS_RETRIES + 1):
        # Increase temperature slightly on retries to escape degenerate modes.
        temperature = 0.1 + (attempt - 1) * 0.15
        llm = ChatOllama(model=model, temperature=temperature, num_ctx=num_ctx, format="json")

        if attempt > 1:
            print(
                f"  [synthesizer] retry {attempt}/{_MAX_SYNTHESIS_RETRIES} "
                f"(prev attempt returned {len(parsed.get('concepts', []))} concepts, "
                f"error={last_error!r})",
                flush=True,
            )
            event_log.step(
                "web_researcher/synthesizer",
                f"synthesize_concept_graph retry {attempt}/{_MAX_SYNTHESIS_RETRIES}",
            )

        raw_response = ""
        error: str | None = None
        attempt_parsed: dict = {
            "concepts": [], "relations": [],
            "aporias": [], "logic_flow": "", "core_frustration": ""
        }

        try:
            _t0 = time.time()
            raw_response = llm.invoke(prompt).content
            event_log.llm(
                "web_researcher/synthesizer",
                f"synthesize_concept_graph (attempt {attempt})",
                model,
                time.time() - _t0,
            )
            attempt_parsed = extract_json(raw_response)
        except (json.JSONDecodeError, ValueError) as e:
            error = f"JSON parse error: {e}"
        except Exception as e:  # noqa: BLE001
            error = f"LLM invocation error: {e}"

        if error is None:
            # Normalise relation_type values before Pydantic validation.
            _normalise_relations(attempt_parsed)

        all_steps.append(create_step(
            layer="web_researcher", node="synthesizer",
            action=f"synthesize_concept_graph (attempt {attempt})",
            input_summary=f"Synthesising from {len(chunks)} web-research chunks",
            llm_prompt=prompt,
            llm_raw_response=raw_response,
            parsed_output=attempt_parsed,
            error=error,
            reasoning=(
                f"Built graph: {len(attempt_parsed.get('concepts', []))} concepts, "
                f"{len(attempt_parsed.get('relations', []))} relations, "
                f"{len(attempt_parsed.get('aporias', []))} aporias"
            ),
        ))

        last_error = error
        if error is None and attempt_parsed.get("concepts"):
            # Success: at least one concept was extracted.
            parsed = attempt_parsed
            break

        # Keep the best result so far (prefer non-empty over empty).
        if len(attempt_parsed.get("concepts", [])) > len(parsed.get("concepts", [])):
            parsed = attempt_parsed
    else:
        # All retries exhausted — log a warning and continue with partial results.
        print(
            f"  [synthesizer] WARNING: all {_MAX_SYNTHESIS_RETRIES} attempts yielded "
            f"{len(parsed.get('concepts', []))} concepts. "
            "Saving partial results and continuing.",
            flush=True,
        )
        event_log.step(
            "web_researcher/synthesizer",
            f"synthesize_concept_graph FAILED after {_MAX_SYNTHESIS_RETRIES} retries "
            f"— partial result: {len(parsed.get('concepts', []))} concepts",
        )

    graph = ConceptGraphV1.from_legacy_dict(
        parsed,
        subject=subject,
        source_mode="web_researcher",
        generated_by="web_researcher",
    )

    return graph, all_steps
