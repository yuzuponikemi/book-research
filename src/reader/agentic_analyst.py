"""Agentic analysis loop: iterative reflection and deepening of chunk analysis.

After the initial analyze_chunk() call, an LLM reflection loop decides whether to
deepen, cross-reference with prior chunks, or reframe through a different lens.
Max 3 reflection iterations per chunk; each iteration produces additional findings
that are merged into the base analysis.
"""

import json
import re

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.reader.analyst import analyze_chunk, _invoke_with_retry


MAX_REFLECT_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

REFLECTION_PROMPT = """\
You are a scholar reviewing your own analysis of a text chunk.

Here is the analysis you have produced so far:
{analysis_summary}

Here is the original text chunk:
{chunk_text_preview}

Reflect on your analysis. Consider:
- Are there concepts or arguments you missed or described too superficially?
- Are there connections to ideas from earlier chunks that you should explore?
  Prior chunk concepts: {prior_concepts_summary}
- Would a different philosophical or analytical lens reveal something new?

Decide your next action. Respond ONLY with valid JSON:
{{
  "action": "<one of: deepen | cross_reference | reframe | finalize>",
  "reasoning": "Brief explanation of why you chose this action",
  "focus_query": "Specific question or focus area for the next analysis step (empty string if finalize)"
}}

Choose "finalize" if your analysis is already thorough and complete.
Choose "deepen" if specific concepts need richer explanation or you missed arguments.
Choose "cross_reference" if earlier chunk concepts connect to this chunk in unexplored ways.
Choose "reframe" if a different analytical perspective would reveal hidden dimensions.
"""

DEEPEN_PROMPT = """\
You are a scholar performing a focused deep-dive on a text.

Your previous analysis identified these concepts and arguments, but they need \
deeper exploration. Focus specifically on: {focus_query}

Relevant passages from the text:
{relevant_passages}

Full text chunk for reference:
{chunk_text}

Extract ADDITIONAL findings that your initial analysis missed. Provide:
- New or enriched concepts (with id, name, description, original_quotes, source_chunk)
- New aporias or tensions discovered
- New relations between concepts
- New argument structures uncovered
- Any rhetorical strategies you now notice

Respond ONLY with valid JSON:
{{
  "concepts": [...],
  "aporias": [...],
  "relations": [...],
  "arguments": [],
  "rhetorical_strategies": []
}}

Only include genuinely NEW findings, not repetitions of what was already extracted.
"""

CROSS_REFERENCE_PROMPT = """\
You are a scholar tracing intellectual connections across a text.

You are analyzing chunk "{part_id}". Here are concepts from EARLIER chunks:
{prior_concepts_detail}

Here is the CURRENT chunk's analysis summary:
{analysis_summary}

Current chunk text:
{chunk_text}

Focus: {focus_query}

Identify connections between this chunk and earlier concepts. Extract:
- New relations (source/target concept IDs, relation_type, evidence)
- Concepts from this chunk that EVOLVE or CONTRADICT earlier ones
- Aporias that span multiple chunks

Respond ONLY with valid JSON:
{{
  "concepts": [],
  "aporias": [...],
  "relations": [...],
  "arguments": [],
  "rhetorical_strategies": []
}}
"""

REFRAME_PROMPT = """\
You are a scholar re-examining a text through a fresh analytical lens.

Your previous analysis approached the text conventionally. Now re-examine it with \
this focus: {focus_query}

Text chunk ({part_id}):
{chunk_text}

Previous analysis summary:
{analysis_summary}

Extract findings that this new perspective reveals — concepts, tensions, arguments, \
or rhetorical strategies that were invisible under the original framing.

Respond ONLY with valid JSON:
{{
  "concepts": [...],
  "aporias": [...],
  "relations": [...],
  "arguments": [],
  "rhetorical_strategies": []
}}

Only include genuinely NEW findings from this reframing, not repetitions.
"""


# ---------------------------------------------------------------------------
# Tool functions (pure Python, no LLM)
# ---------------------------------------------------------------------------

def reread_section(chunk_text: str, focus_query: str) -> str:
    """Extract paragraphs from chunk_text that are relevant to focus_query.

    Simple keyword-matching approach: split query into words, score each
    paragraph by keyword overlap, return top paragraphs.
    """
    keywords = set(re.findall(r'\w{4,}', focus_query.lower()))
    if not keywords:
        return chunk_text[:3000]

    paragraphs = [p.strip() for p in chunk_text.split('\n\n') if p.strip()]
    if not paragraphs:
        return chunk_text[:3000]

    scored = []
    for para in paragraphs:
        para_lower = para.lower()
        score = sum(1 for kw in keywords if kw in para_lower)
        scored.append((score, para))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Return top paragraphs up to ~3000 chars
    result = []
    total = 0
    for score, para in scored:
        if score == 0 and result:
            break
        result.append(para)
        total += len(para)
        if total > 3000:
            break

    return '\n\n'.join(result) if result else chunk_text[:3000]


def recall_previous_concepts(prior_analyses: list[dict], query: str) -> str:
    """Search prior chunk analyses for concepts related to query.

    Returns a formatted string of matching concepts with their descriptions.
    """
    if not prior_analyses:
        return "(no prior chunks analyzed yet)"

    keywords = set(re.findall(r'\w{4,}', query.lower()))
    matches = []

    for i, analysis in enumerate(prior_analyses):
        for concept in analysis.get('concepts', []):
            if isinstance(concept, str):
                continue
            name = concept.get('name', '').lower()
            desc = concept.get('description', '').lower()
            cid = concept.get('id', '')
            text = f"{name} {desc} {cid}"
            score = sum(1 for kw in keywords if kw in text)
            if score > 0 or not keywords:
                matches.append((score, i, concept))

    matches.sort(key=lambda x: x[0], reverse=True)

    lines = []
    for score, chunk_idx, concept in matches[:10]:
        lines.append(
            f"- [{concept.get('id', '?')}] {concept.get('name', '?')} "
            f"(chunk {chunk_idx+1}): {concept.get('description', '')[:150]}"
        )

    return '\n'.join(lines) if lines else "(no matching concepts found)"


def get_analysis_summary(analysis: dict) -> str:
    """Format current analysis into a concise readable summary for reflection."""
    lines = []

    concepts = analysis.get('concepts', [])
    if concepts:
        lines.append(f"Concepts ({len(concepts)}):")
        for c in concepts:
            if isinstance(c, str):
                lines.append(f"  - {c[:100]}")
            else:
                lines.append(f"  - {c.get('name', '?')}: {c.get('description', '')[:120]}")

    aporias = analysis.get('aporias', [])
    if aporias:
        lines.append(f"Aporias ({len(aporias)}):")
        for a in aporias:
            if isinstance(a, str):
                lines.append(f"  - {a[:100]}")
            else:
                lines.append(f"  - {a.get('question', '?')}")

    args = analysis.get('arguments', [])
    if args:
        lines.append(f"Arguments ({len(args)}):")
        for arg in args:
            if isinstance(arg, str):
                lines.append(f"  - {arg[:100]}")
            else:
                lines.append(f"  - {arg.get('id', '?')}: {arg.get('conclusion', '')[:100]}")

    logic = analysis.get('logic_flow', '')
    if logic:
        lines.append(f"Logic flow: {logic[:200]}")

    return '\n'.join(lines)


def _get_prior_concepts_summary(prior_analyses: list[dict]) -> str:
    """One-line-per-concept summary of all prior chunk concepts."""
    if not prior_analyses:
        return "(first chunk — no prior concepts)"

    items = []
    for i, analysis in enumerate(prior_analyses):
        for c in analysis.get('concepts', []):
            if isinstance(c, str):
                continue
            items.append(f"{c.get('id', '?')} ({c.get('name', '?')}, chunk {i+1})")

    return ', '.join(items[:20]) if items else "(no concepts extracted from prior chunks)"


def _get_prior_concepts_detail(prior_analyses: list[dict]) -> str:
    """Detailed listing of prior concepts for cross-reference prompt."""
    if not prior_analyses:
        return "(no prior chunks)"

    lines = []
    for i, analysis in enumerate(prior_analyses):
        for c in analysis.get('concepts', []):
            if isinstance(c, str):
                continue
            lines.append(
                f"[chunk {i+1}] {c.get('id', '?')} — {c.get('name', '?')}: "
                f"{c.get('description', '')[:200]}"
            )
    return '\n'.join(lines[:30]) if lines else "(no prior concepts)"


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def _merge_findings(base: dict, new: dict) -> dict:
    """Merge new findings into base analysis, deduplicating by concept ID."""
    merged = {k: list(v) if isinstance(v, list) else v
              for k, v in base.items()}

    # Merge concepts — deduplicate by id
    existing_ids = set()
    for c in merged.get('concepts', []):
        if isinstance(c, dict):
            existing_ids.add(c.get('id', ''))

    for c in new.get('concepts', []):
        if isinstance(c, dict) and c.get('id', '') not in existing_ids:
            merged.setdefault('concepts', []).append(c)
            existing_ids.add(c['id'])

    # Merge aporias — deduplicate by id
    existing_aporia_ids = set()
    for a in merged.get('aporias', []):
        if isinstance(a, dict):
            existing_aporia_ids.add(a.get('id', ''))

    for a in new.get('aporias', []):
        if isinstance(a, dict) and a.get('id', '') not in existing_aporia_ids:
            merged.setdefault('aporias', []).append(a)
            existing_aporia_ids.add(a['id'])

    # Merge relations — deduplicate by (source, target, relation_type)
    existing_rels = set()
    for r in merged.get('relations', []):
        if isinstance(r, dict):
            existing_rels.add((r.get('source', ''), r.get('target', ''),
                               r.get('relation_type', '')))

    for r in new.get('relations', []):
        if isinstance(r, dict):
            key = (r.get('source', ''), r.get('target', ''),
                   r.get('relation_type', ''))
            if key not in existing_rels:
                merged.setdefault('relations', []).append(r)
                existing_rels.add(key)

    # Merge arguments — deduplicate by id
    existing_arg_ids = set()
    for a in merged.get('arguments', []):
        if isinstance(a, dict):
            existing_arg_ids.add(a.get('id', ''))

    for a in new.get('arguments', []):
        if isinstance(a, dict) and a.get('id', '') not in existing_arg_ids:
            merged.setdefault('arguments', []).append(a)
            existing_arg_ids.add(a['id'])

    # Merge rhetorical_strategies — deduplicate by id
    existing_rs_ids = set()
    for rs in merged.get('rhetorical_strategies', []):
        if isinstance(rs, dict):
            existing_rs_ids.add(rs.get('id', ''))

    for rs in new.get('rhetorical_strategies', []):
        if isinstance(rs, dict) and rs.get('id', '') not in existing_rs_ids:
            merged.setdefault('rhetorical_strategies', []).append(rs)
            existing_rs_ids.add(rs['id'])

    return merged


# ---------------------------------------------------------------------------
# Main agentic loop
# ---------------------------------------------------------------------------

def analyze_chunk_agentic(
    chunk_text: str,
    part_id: str,
    llm: ChatOllama,
    prior_analyses: list[dict] | None = None,
    key_terms: list[str] | None = None,
) -> tuple[dict, list[dict]]:
    """Analyze a chunk with iterative reflection.

    Returns (merged_analysis, list_of_thinking_steps).
    """
    prior_analyses = prior_analyses or []
    steps = []

    # Step 1: Initial analysis (reuse existing function)
    analysis, initial_step = analyze_chunk(chunk_text, part_id, llm,
                                           key_terms=key_terms)
    steps.append(initial_step)

    # Step 2: Reflection loop
    for iteration in range(MAX_REFLECT_ITERATIONS):
        # Ask LLM to reflect
        analysis_summary = get_analysis_summary(analysis)
        prior_summary = _get_prior_concepts_summary(prior_analyses)

        reflect_prompt = REFLECTION_PROMPT.format(
            analysis_summary=analysis_summary,
            chunk_text_preview=chunk_text[:2000],
            prior_concepts_summary=prior_summary,
        )

        raw_reflect = _invoke_with_retry(llm, reflect_prompt, part_id)

        # Parse reflection
        try:
            reflection = extract_json(raw_reflect)
        except (json.JSONDecodeError, ValueError):
            reflection = {"action": "finalize", "reasoning": "parse error",
                          "focus_query": ""}

        action = reflection.get("action", "finalize")
        focus_query = reflection.get("focus_query", "")
        reasoning = reflection.get("reasoning", "")

        reflect_step = create_step(
            layer="reader",
            node="agentic_analyst",
            action=f"reflect:{part_id}:iter{iteration+1}",
            input_summary=f"Reflection iteration {iteration+1} for {part_id}",
            llm_prompt=reflect_prompt,
            llm_raw_response=raw_reflect,
            parsed_output=reflection,
            reasoning=f"Action={action}: {reasoning}",
        )
        steps.append(reflect_step)

        if action == "finalize":
            print(f" [reflect {iteration+1}: finalize]", end="", flush=True)
            break

        print(f" [reflect {iteration+1}: {action}]", end="", flush=True)

        # Dispatch based on action
        new_findings = None
        tool_prompt = ""

        if action == "deepen":
            relevant = reread_section(chunk_text, focus_query)
            tool_prompt = DEEPEN_PROMPT.format(
                focus_query=focus_query,
                relevant_passages=relevant,
                chunk_text=chunk_text[:15000],
            )

        elif action == "cross_reference":
            prior_detail = _get_prior_concepts_detail(prior_analyses)
            tool_prompt = CROSS_REFERENCE_PROMPT.format(
                part_id=part_id,
                prior_concepts_detail=prior_detail,
                analysis_summary=analysis_summary,
                chunk_text=chunk_text[:15000],
                focus_query=focus_query,
            )

        elif action == "reframe":
            tool_prompt = REFRAME_PROMPT.format(
                focus_query=focus_query,
                part_id=part_id,
                chunk_text=chunk_text[:15000],
                analysis_summary=analysis_summary,
            )

        else:
            # Unknown action → treat as finalize
            break

        # Execute the tool prompt
        raw_tool = _invoke_with_retry(llm, tool_prompt, part_id)

        try:
            new_findings = extract_json(raw_tool)
        except (json.JSONDecodeError, ValueError):
            new_findings = None

        tool_step = create_step(
            layer="reader",
            node="agentic_analyst",
            action=f"{action}:{part_id}:iter{iteration+1}",
            input_summary=f"{action} on {part_id} — focus: {focus_query[:80]}",
            llm_prompt=tool_prompt,
            llm_raw_response=raw_tool,
            parsed_output=new_findings,
            reasoning=f"Executed {action} for: {focus_query[:100]}",
        )
        steps.append(tool_step)

        # Merge findings
        if new_findings:
            before_concepts = len(analysis.get('concepts', []))
            analysis = _merge_findings(analysis, new_findings)
            after_concepts = len(analysis.get('concepts', []))
            delta = after_concepts - before_concepts
            if delta > 0:
                print(f" (+{delta} concepts)", end="", flush=True)

    return analysis, steps
