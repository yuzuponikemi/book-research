"""Merge chunk-level analyses into a unified ConceptGraph."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.models import ConceptGraph


SYNTHESIS_PROMPT = """\
You are synthesizing multiple chunk-level analyses into a unified concept graph.

Below are analyses from {chunk_count} chunks of {work_description}.

IMPORTANT: Preserve richness. The final graph should have 10-20 unified concepts, NOT fewer. \
Only merge concepts that are truly the same idea. Different aspects of a broad concept \
(e.g., "concept X as theoretical framework" vs "concept X applied in practice") \
should remain as separate concepts with a relation between them.

Your tasks:

1. **Deduplicate concepts**: If the EXACT SAME concept appears across chunks (possibly \
with different names), merge them. Keep the richest description and ALL unique quotes. \
For each merged concept, set source_chunk to "COMBINED" and note which parts it spans.
   - Do NOT merge concepts that are merely related — only true duplicates.
   - Aim for 10-20 concepts in the final graph.

2. **Build cross-chunk relations**: Identify ALL conceptual dependencies across chunks. \
Trace the full chain of how ideas build on, contradict, or evolve from each other. \
Map every significant dependency.
   - Aim for at least 8-12 relations.

3. **Identify the core frustration**: What is the single driving tension of the entire work? \
This is NOT a summary. It's the unresolved intellectual itch that the author cannot fully \
scratch, the question that haunts every chapter.

4. **Preserve ALL aporias**: Merge duplicates but keep distinct tensions separate. \
Aim for 4-8 aporias in the final graph.

5. **Create the unified logic flow**: A detailed narrative (at least 6-8 sentences) tracing \
the entire reasoning chain from beginning to end. Explain what drives each transition.

CHUNK ANALYSES:
{analyses_json}

Respond ONLY with valid JSON in this exact structure:
{{
  "concepts": [
    {{"id": "...", "name": "...", "description": "...", "original_quotes": ["..."], "source_chunk": "..."}}
  ],
  "relations": [
    {{"source": "...", "target": "...", "relation_type": "depends_on|contradicts|evolves_into", "evidence": "..."}}
  ],
  "aporias": [
    {{"id": "...", "question": "...", "context": "...", "related_concepts": ["..."]}}
  ],
  "logic_flow": "...",
  "core_frustration": "..."
}}
"""


def synthesize(state: dict) -> dict:
    """LangGraph node: merge chunk analyses into a unified ConceptGraph."""
    chunk_analyses = state["chunk_analyses"]
    steps = list(state.get("thinking_log", []))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=32768, format="json")

    # Prepare a condensed version of analyses for the prompt
    analyses_summary = []
    for i, analysis in enumerate(chunk_analyses):
        analyses_summary.append({
            "chunk_index": i,
            "concepts": analysis.get("concepts", []),
            "aporias": analysis.get("aporias", []),
            "relations": analysis.get("relations", []),
            "logic_flow": analysis.get("logic_flow", ""),
        })

    analyses_json = json.dumps(analyses_summary, ensure_ascii=False, indent=2)
    # Truncate if too long for context window
    if len(analyses_json) > 25000:
        analyses_json = analyses_json[:25000] + "\n... (truncated)"

    book_config = state.get("book_config", {})
    book = book_config.get("book", {})
    pf = book_config.get("prompt_fragments", {})
    work_description = pf.get(
        "work_description",
        f'{book.get("author", "the author")}\'s "{book.get("title", state.get("book_title", "this work"))}"'
    )

    prompt = SYNTHESIS_PROMPT.format(
        chunk_count=len(chunk_analyses),
        analyses_json=analyses_json,
        work_description=work_description,
    )

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
        ConceptGraph(**parsed)
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = parsed or {
            "concepts": [],
            "relations": [],
            "aporias": [],
            "logic_flow": "",
            "core_frustration": "",
        }
    except Exception as e:
        error = f"Validation error: {e}"

    steps.append(create_step(
        layer="reader",
        node="synthesizer",
        action="merge_concept_graph",
        input_summary=f"Merging {len(chunk_analyses)} chunk analyses",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Synthesized {len(parsed.get('concepts', []))} concepts, "
                  f"{len(parsed.get('relations', []))} relations, "
                  f"{len(parsed.get('aporias', []))} aporias into unified graph",
    ))

    return {
        "concept_graph": parsed,
        "thinking_log": steps,
    }
