"""Analyst service — merge chunk analyses → ConceptGraphV1.

Ported and decoupled from src/reader/synthesizer.py.
CogitoState dependency removed; takes plain arguments.
"""

from __future__ import annotations

import json
from typing import Literal

import time

from langchain_ollama import ChatOllama

from cogito.utils.logger import create_step, extract_json
from cogito.utils import event_log
from cogito.schemas.concept_graph import ConceptGraphV1


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


def synthesize_concept_graph(
    chunk_analyses: list[dict],
    work_description: str,
    subject: str,
    model: str = "llama3",
    source_mode: Literal["book", "web_researcher"] = "book",
) -> tuple[ConceptGraphV1, list[dict]]:
    """Merge chunk analyses into a unified ConceptGraphV1.

    Args:
        chunk_analyses:   Output of extractor.extract_all_chunks().
        work_description: Human-readable description used in the LLM prompt.
        subject:          Short identifier stored in the schema (e.g. '方法序説').
        model:            Ollama model name.
        source_mode:      Origin route recorded in the schema.

    Returns:
        (ConceptGraphV1, thinking_log_entries)
    """
    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=num_ctx, format="json")

    analyses_summary = [
        {
            "chunk_index": i,
            "concepts": a.get("concepts", []),
            "aporias": a.get("aporias", []),
            "relations": a.get("relations", []),
            "logic_flow": a.get("logic_flow", ""),
        }
        for i, a in enumerate(chunk_analyses)
    ]

    analyses_json = json.dumps(analyses_summary, ensure_ascii=False, indent=2)
    if len(analyses_json) > 25000:
        analyses_json = analyses_json[:25000] + "\n... (truncated)"

    prompt = SYNTHESIS_PROMPT.format(
        chunk_count=len(chunk_analyses),
        analyses_json=analyses_json,
        work_description=work_description,
    )

    _t0 = time.time()
    raw_response = llm.invoke(prompt).content
    event_log.llm("analyst/synthesizer", "synthesize_concept_graph", model, time.time() - _t0)

    parsed: dict | None = None
    error: str | None = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {
            "concepts": [],
            "relations": [],
            "aporias": [],
            "logic_flow": "",
            "core_frustration": "",
        }

    step = create_step(
        layer="analyst",
        node="synthesizer",
        action="synthesize_concept_graph",
        input_summary=f"Merging {len(chunk_analyses)} chunk analyses",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=(
            f"Synthesized {len(parsed.get('concepts', []))} concepts, "
            f"{len(parsed.get('relations', []))} relations, "
            f"{len(parsed.get('aporias', []))} aporias"
        ),
    )

    graph = ConceptGraphV1.from_legacy_dict(
        parsed,
        subject=subject,
        source_mode=source_mode,
        generated_by="analyst",
    )

    return graph, [step]
