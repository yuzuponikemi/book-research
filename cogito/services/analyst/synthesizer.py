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
You are synthesizing multiple chunk-level analyses into a rich, unified concept graph.

Below are analyses from {chunk_count} chunks of {work_description}.

PHILOSOPHY: This graph is the intellectual backbone of a deep reading. \
Every relation and every aporia is a thread the scriptwriter will pull. \
If you discard a relation or aporia, it will NEVER appear in the final output. \
When in doubt, KEEP IT.

## Task 1: Deduplicate concepts (CONSERVATIVE — only true duplicates)

Merge ONLY if two concepts are literally the same idea under different names. \
Do NOT merge because they are related, overlapping, or thematically similar.

- Keep ALL unique concepts. Aim for **12-20 concepts** in the final graph.
- For merged concepts, keep the richest description and ALL unique original_quotes combined.
- Set source_chunk to "COMBINED (PART X + PART Y)" for merged concepts.
- Write each description in 3-5 sentences: what it is, why the author introduces it, \
  what problem it solves, and how it evolves through the work.

## Task 2: Build the full relation map (MAXIMIZE — keep all significant connections)

Map EVERY meaningful conceptual relationship across ALL chunks.
- **Minimum: 10 relations. Aim for 12-18.**
- Include both intra-chunk relations (from individual chunks) AND new cross-chunk \
  relations you discover when seeing the complete picture together.
- For each relation, write a 2-3 sentence evidence explaining the intellectual link.
- Relation types:
  - "depends_on": concept A only makes sense once concept B is established
  - "contradicts": concept A and concept B are in genuine, unresolved tension
  - "evolves_into": concept A develops or transforms into concept B over the course of the work

## Task 3: Preserve ALL distinct aporias (MAXIMIZE — keep all unresolved tensions)

An aporia is a genuine intellectual impasse the author cannot fully resolve. \
- Keep ALL distinct aporias. **Minimum: 5 aporias. Aim for 6-10.**
- Merge ONLY if two aporias are literally asking the exact same question.
- For each aporia, write a 3-4 sentence context: what has been tried, \
  why it remains unresolved, and what is at stake.

## Task 4: Core frustration

The single driving tension that haunts the entire work — the question the author \
urgently wanted to answer but could not fully resolve. Write 3-4 sentences.

## Task 5: Unified logic flow

A narrative of 8-12 sentences tracing the full argumentative arc: from the opening \
problem through each major conceptual move to the final (unresolved) conclusion. \
Explain WHAT motivates each transition.

---

CHUNK ANALYSES:
{analyses_json}

Respond ONLY with valid JSON:
{{
  "concepts": [
    {{
      "id": "snake_case_id",
      "name": "Display Name",
      "description": "Rich 3-5 sentence explanation...",
      "original_quotes": ["direct quote 1", "direct quote 2"],
      "source_chunk": "PART I or COMBINED (PART I + PART II)"
    }}
  ],
  "relations": [
    {{
      "source": "concept_id_a",
      "target": "concept_id_b",
      "relation_type": "depends_on",
      "evidence": "2-3 sentence explanation of the intellectual link..."
    }}
  ],
  "aporias": [
    {{
      "id": "snake_case_id",
      "question": "The tension stated as a penetrating question?",
      "context": "3-4 sentence explanation of why this remains unresolved...",
      "related_concepts": ["concept_id_1", "concept_id_2"]
    }}
  ],
  "logic_flow": "8-12 sentence narrative of the full argumentative arc...",
  "core_frustration": "3-4 sentence description of the single driving tension..."
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
