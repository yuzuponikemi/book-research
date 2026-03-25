"""Per-chunk concept extraction — extracted from src/reader/analyst.py.

Changes from the original:
- No CogitoState dependency; takes plain arguments instead.
- Returns pure data (dict, step_log); no LangGraph specifics.
- key_terms and model selection remain configurable via arguments.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_ollama import ChatOllama

from cogito.utils import event_log

from cogito.utils.logger import create_step, extract_json


MAX_RETRIES = 3


ANALYSIS_PROMPT = """\
You are a scholar performing deep analytical reading of a text.

Your task is to analyze the following text chunk and extract its FULL intellectual structure.
Do NOT write a summary. Extract the complete REASONING PROCESS with maximum depth:

1. **Concepts** (extract ALL significant concepts and ideas, typically 5-10 per chunk):
   For each concept, provide:
   - id: a snake_case slug (e.g., "social_contract")
   - name: display name
   - description: a rich, detailed explanation of what this concept means in the author's framework (at least 2-3 sentences). Explain WHY the author introduces it, what problem it solves, and how it fits into the larger argument.
   - original_quotes: 2-4 direct quotes from the text that ground this concept. Use the most significant passages, not just mentions.
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

5. **Argument Structures**: Extract the formal arguments in this chunk (typically 1-4). \
For each, provide:
   - id: a snake_case slug (e.g., "central_thesis_argument")
   - premises: list of premise statements
   - conclusion: the conclusion drawn
   - argument_type: "deductive" | "inductive" | "analogical"
   - source_chunk: "{part_id}"

6. **Named Techniques or Frameworks**: Identify any well-known techniques, \
methods, frameworks, or named strategies used by the author. {key_terms_instruction}

7. **Rhetorical Strategies**: Identify metaphors, analogies, thought experiments, or \
appeals to authority used to persuade the reader (typically 1-3). For each, provide:
   - id: a snake_case slug
   - strategy_type: "metaphor" | "analogy" | "thought_experiment" | "appeal_to_authority"
   - description: what the strategy does and why it's effective
   - original_quote: the relevant passage
   - source_chunk: "{part_id}"

Be thorough. It is better to extract too many concepts than too few.

Respond ONLY with valid JSON in this exact structure:
{{
  "concepts": [...],
  "aporias": [...],
  "relations": [...],
  "logic_flow": "...",
  "arguments": [...],
  "rhetorical_strategies": [...]
}}

TEXT CHUNK ({part_id}):
{text}
"""


def _invoke_with_retry(llm: ChatOllama, prompt: str, label: str,
                       max_retries: int = MAX_RETRIES) -> str:
    """Invoke LLM with retry logic to handle Ollama hangs."""
    _t0 = time.time()
    for attempt in range(max_retries):
        try:
            result = llm.invoke(prompt).content
            event_log.llm("analyst/extractor", label, llm.model, time.time() - _t0)
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                print(f" [timeout/error on attempt {attempt+1}, retrying in {wait}s: {e}]",
                      end="", flush=True)
                time.sleep(wait)
            else:
                raise


def extract_chunk(
    chunk_text: str,
    part_id: str,
    llm: ChatOllama,
    key_terms: list[str] | None = None,
) -> tuple[dict, dict]:
    """Analyse a single text chunk.

    Args:
        chunk_text: Raw text of the chunk.
        part_id:    Identifier for the chunk (e.g. "PART IV").
        llm:        Configured ChatOllama instance.
        key_terms:  Optional list of expected concepts to look for.

    Returns:
        (analysis_dict, step_log_dict) — pure data, no LangGraph state.
    """
    key_terms_instruction = (
        f"Look especially for these known terms/techniques: {', '.join(key_terms)}"
        if key_terms else ""
    )

    prompt = ANALYSIS_PROMPT.format(
        part_id=part_id,
        text=chunk_text[:20000],
        key_terms_instruction=key_terms_instruction,
    )

    raw_response = _invoke_with_retry(llm, prompt, part_id)

    parsed: dict | None = None
    error: str | None = None
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
        layer="analyst",
        node="extractor",
        action=f"extract_chunk:{part_id}",
        input_summary=f"Chunk '{part_id}': {len(chunk_text)} chars",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=(
            f"Extracted {len(parsed.get('concepts', []))} concepts, "
            f"{len(parsed.get('aporias', []))} aporias, "
            f"{len(parsed.get('relations', []))} relations from {part_id}"
        ),
    )

    return parsed, step


def extract_all_chunks(
    chunks: list[tuple[str, str]],  # [(part_id, text), ...]
    model: str = "llama3",
    key_terms: list[str] | None = None,
    max_workers: int = 4,
) -> tuple[list[dict], list[dict]]:
    """Analyse all chunks in parallel.

    Args:
        chunks:      List of (part_id, text) tuples.
        model:       Ollama model name.
        key_terms:   Optional list of expected concept terms.
        max_workers: Number of parallel threads (default: 4).

    Returns:
        (chunk_analyses, thinking_log)
    """
    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    _is_thinking = any(m in model.lower() for m in ("qwen3", "qwq", "deepseek-r1"))
    llm = ChatOllama(
        model=model, temperature=0.1, num_ctx=num_ctx,
        **({"format": "json"} if _is_thinking else {}),
    )

    n = len(chunks)
    print(f"      Parallel extraction: {n} chunks, max_workers={max_workers}")

    results: dict[int, tuple[dict, dict]] = {}

    def _run(idx: int, part_id: str, text: str) -> tuple[int, dict, dict]:
        analysis, step = extract_chunk(text, part_id, llm, key_terms=key_terms)
        n_c = len(analysis.get("concepts", []))
        n_a = len(analysis.get("aporias", []))
        print(f"      [{idx+1}/{n}] ✓ {part_id}: {n_c} concepts, {n_a} aporias", flush=True)
        return idx, analysis, step

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run, i, part_id, text): i
            for i, (part_id, text) in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx, analysis, step = future.result()
            results[idx] = (analysis, step)

    # Reassemble in original order
    analyses = [results[i][0] for i in range(n)]
    log = [results[i][1] for i in range(n)]

    return analyses, log
