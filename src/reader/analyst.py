"""Per-chunk concept extraction via Ollama."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json


ANALYSIS_PROMPT = """\
You are a philosopher performing deep hermeneutic analysis of a philosophical text.

Your task is to analyze the following text chunk and extract its FULL intellectual structure.
Do NOT write a summary. Extract the complete REASONING PROCESS with maximum depth:

1. **Concepts** (extract ALL significant philosophical concepts, typically 5-10 per chunk):
   For each concept, provide:
   - id: a snake_case slug (e.g., "methodical_doubt")
   - name: display name
   - description: a rich, detailed explanation of what this concept means in the author's framework (at least 2-3 sentences). Explain WHY the author introduces it, what problem it solves, and how it fits into the larger argument.
   - original_quotes: 2-4 direct quotes from the text that ground this concept. Use the most philosophically significant passages, not just mentions.
   - source_chunk: "{part_id}"

2. **Aporias** (extract ALL unresolved tensions, typically 2-4 per chunk):
   For each, provide:
   - id: a snake_case slug
   - question: the tension stated as a penetrating question
   - context: a detailed explanation of why this question arises, what the author has tried, and why it remains unresolved (2-3 sentences)
   - related_concepts: list of concept IDs involved

3. **Relations** (map ALL conceptual dependencies):
   For each, provide:
   - source: concept ID
   - target: concept ID
   - relation_type: one of "depends_on", "contradicts", "evolves_into"
   - evidence: a detailed explanation of why this relation exists, citing the author's reasoning

4. **Logic flow**: A detailed narrative (at least 4-5 sentences) tracing the author's reasoning chain step by step through this chunk. Explain what motivates each move in the argument.

Be thorough. It is better to extract too many concepts than too few.

Respond ONLY with valid JSON in this exact structure:
{{
  "concepts": [...],
  "aporias": [...],
  "relations": [...],
  "logic_flow": "..."
}}

TEXT CHUNK ({part_id}):
{text}
"""


def analyze_chunk(chunk_text: str, part_id: str, llm: ChatOllama) -> tuple[dict, dict]:
    """Analyze a single chunk, returning (analysis_dict, step_log_dict)."""
    prompt = ANALYSIS_PROMPT.format(
        part_id=part_id,
        text=chunk_text[:20000],  # command-r has 128K context; llama3 has 8K
    )

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {
            "concepts": [],
            "aporias": [],
            "relations": [],
            "logic_flow": raw_response[:500],
        }

    step = create_step(
        layer="reader",
        node="analyst",
        action=f"analyze_chunk:{part_id}",
        input_summary=f"Chunk '{part_id}': {len(chunk_text)} chars",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Extracted {len(parsed.get('concepts', []))} concepts, "
                  f"{len(parsed.get('aporias', []))} aporias, "
                  f"{len(parsed.get('relations', []))} relations from {part_id}",
    )

    return parsed, step


def analyze_chunks(state: dict) -> dict:
    """LangGraph node: analyze all chunks sequentially."""
    raw_chunks = state["raw_chunks"]
    steps = list(state.get("thinking_log", []))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=16384, format="json")

    chunk_analyses = []
    for i, chunk_text in enumerate(raw_chunks):
        # Extract part_id from the chunk text (first line typically has "PART X")
        lines = chunk_text.strip().split("\n")
        part_id = lines[0].strip() if lines else f"chunk_{i}"

        print(f"      [{i+1}/{len(raw_chunks)}] Analyzing {part_id}...", end="", flush=True)
        analysis, step = analyze_chunk(chunk_text, part_id, llm)
        n_c = len(analysis.get("concepts", []))
        n_a = len(analysis.get("aporias", []))
        print(f" {n_c} concepts, {n_a} aporias")
        chunk_analyses.append(analysis)
        steps.append(step)

    return {
        "chunk_analyses": chunk_analyses,
        "thinking_log": steps,
    }
