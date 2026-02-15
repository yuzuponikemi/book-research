"""Per-chunk concept extraction via Ollama."""

import json
import time

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json


MAX_RETRIES = 3
TIMEOUT_SECONDS = 600  # 10 minutes per chunk


def _invoke_with_retry(llm, prompt, part_id, max_retries=MAX_RETRIES):
    """Invoke LLM with timeout and retry logic to handle Ollama hangs."""
    for attempt in range(max_retries):
        try:
            return llm.invoke(prompt).content
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                print(f" [timeout/error on attempt {attempt+1}, retrying in {wait}s: {e}]",
                      end="", flush=True)
                time.sleep(wait)
            else:
                raise


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


def analyze_chunk(chunk_text: str, part_id: str, llm: ChatOllama,
                   key_terms: list[str] | None = None) -> tuple[dict, dict]:
    """Analyze a single chunk, returning (analysis_dict, step_log_dict)."""
    if key_terms:
        key_terms_instruction = (
            f"Look especially for these known terms/techniques: {', '.join(key_terms)}"
        )
    else:
        key_terms_instruction = ""

    prompt = ANALYSIS_PROMPT.format(
        part_id=part_id,
        text=chunk_text[:20000],  # command-r has 128K context; llama3 has 8K
        key_terms_instruction=key_terms_instruction,
    )

    raw_response = _invoke_with_retry(llm, prompt, part_id)

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
                  f"{len(parsed.get('relations', []))} relations, "
                  f"{len(parsed.get('arguments', []))} arguments, "
                  f"{len(parsed.get('rhetorical_strategies', []))} rhetorical strategies "
                  f"from {part_id}",
    )

    return parsed, step


def analyze_chunks(state: dict) -> dict:
    """LangGraph node: analyze all chunks sequentially."""
    raw_chunks = state["raw_chunks"]
    steps = list(state.get("thinking_log", []))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=16384, format="json")

    # Get key_terms from book_config if available
    book_config = state.get("book_config", {})
    key_terms = book_config.get("context", {}).get("key_terms", [])

    chunk_analyses = []
    for i, chunk_text in enumerate(raw_chunks):
        # Extract part_id from the chunk text (first line typically has "PART X")
        lines = chunk_text.strip().split("\n")
        part_id = lines[0].strip() if lines else f"chunk_{i}"

        print(f"      [{i+1}/{len(raw_chunks)}] Analyzing {part_id}...", end="", flush=True)
        analysis, step = analyze_chunk(chunk_text, part_id, llm, key_terms=key_terms)
        n_c = len(analysis.get("concepts", []))
        n_a = len(analysis.get("aporias", []))
        print(f" {n_c} concepts, {n_a} aporias")
        chunk_analyses.append(analysis)
        steps.append(step)

    return {
        "chunk_analyses": chunk_analyses,
        "thinking_log": steps,
    }
