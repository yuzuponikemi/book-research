"""Producer service — planner stage (Director layer).

Ported and decoupled from src/director/planner.py.
CogitoState dependency removed; takes ConceptGraphV1 directly.
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.schemas.production import SyllabusV1


# ── Prompts (identical to src/director/planner.py) ───────────────────────────

ESSENCE_PROMPT = """\
You are a podcast director designing a single, powerful episode about a notable work.

Given the concept graph below, select the SINGLE most important aporia (unresolved tension) \
and the 2-3 core concepts most essential to understanding it. This episode should capture \
the beating heart of the entire work.

IMPORTANT: Write ALL output in English. Do NOT write in Japanese.

CONCEPT GRAPH:
{concept_graph_json}

Design one episode with:
- title: A compelling English title that captures the episode's essence
- theme: The central tension explored (in English)
- concept_ids: The 2-3 most important concept IDs (must match IDs from the concept graph)
- aporia_ids: The 1-2 most important aporia IDs (must match IDs from the concept graph)
- cliffhanger: A thought-provoking question to leave listeners with (in English)
- cognitive_bridge: How this idea connects to modern life — technology, AI, social media, etc. (in English)

Also provide:
- meta_narrative: A one-sentence description of the overall story arc (in English)

Respond ONLY with valid JSON:
{{
  "mode": "essence",
  "episodes": [
    {{
      "episode_number": 1,
      "title": "...",
      "theme": "...",
      "concept_ids": ["..."],
      "aporia_ids": ["..."],
      "cliffhanger": "...",
      "cognitive_bridge": "..."
    }}
  ],
  "meta_narrative": "..."
}}
"""

CURRICULUM_PROMPT = """\
You are a podcast director designing a multi-episode curriculum about \
{work_description}.

Given the concept graph below, create EXACTLY 6 episodes that follow the logical \
progression of the original text. Each episode should build progressively from \
foundational ideas to the most complex, following the author's own argumentative arc.

IMPORTANT: Write ALL output in English. Do NOT write in Japanese.
IMPORTANT: Base your episode design SOLELY on the concept graph provided below. \
Do NOT introduce concepts, themes, or arguments that are not present in the graph.

{key_terms_guidance}

Episode design principles:
- Episode 1 should introduce the problem or motivation that drives the work
- Episodes 2-5 should develop the core arguments, each building on the previous
- Episode 6 should address implications, applications, or unresolved tensions
- The progression should reflect the internal logic of the work, not an arbitrary division

Guidelines for each episode:
- Focus on 2-4 concepts and 1-2 aporias from the concept graph
- Every episode needs a strong cliffhanger that motivates the next episode
- Cognitive bridges should be specific and modern (AI, social media, startups, bioethics, etc.)
- Each episode must connect back to the overall narrative arc

CONCEPT GRAPH:
{concept_graph_json}

For each episode, design:
- title: A compelling English title
- theme: The central tension explored (in English)
- concept_ids: Which concept IDs this episode covers
- aporia_ids: Which aporia IDs this episode engages with
- cliffhanger: A question that makes listeners need the next episode
- cognitive_bridge: How this idea connects to modern life

Also provide:
- meta_narrative: The overarching story told across all episodes (in English)

Respond ONLY with valid JSON:
{{
  "mode": "curriculum",
  "episodes": [
    {{
      "episode_number": 1,
      "title": "...",
      "theme": "...",
      "concept_ids": ["..."],
      "aporia_ids": ["..."],
      "cliffhanger": "...",
      "cognitive_bridge": "..."
    }}
  ],
  "meta_narrative": "..."
}}
"""

TOPIC_PROMPT = """\
You are a podcast director designing a focused episode about a specific topic within \
{work_description}.

Given the concept graph and the requested topic "{topic}", filter the graph to find the \
most relevant concepts and aporias. Create 1-2 episodes that deeply explore this topic.

IMPORTANT: Write ALL output in English. Do NOT write in Japanese.

CONCEPT GRAPH:
{concept_graph_json}

REQUESTED TOPIC: {topic}

For each episode, design:
- title, theme, concept_ids, aporia_ids, cliffhanger, cognitive_bridge (all in English)

Also provide:
- meta_narrative: The story arc for this topic exploration (in English)

Respond ONLY with valid JSON:
{{
  "mode": "topic",
  "episodes": [
    {{
      "episode_number": 1,
      "title": "...",
      "theme": "...",
      "concept_ids": ["..."],
      "aporia_ids": ["..."],
      "cliffhanger": "...",
      "cognitive_bridge": "..."
    }}
  ],
  "meta_narrative": "..."
}}
"""


def plan_syllabus(
    graph: ConceptGraphV1,
    mode: Literal["essence", "curriculum", "topic"] = "essence",
    topic: str | None = None,
    work_description: str | None = None,
    key_terms: list[str] | None = None,
    enrichment: dict | None = None,
    model: str = "llama3",
) -> tuple[SyllabusV1, list[dict]]:
    """Generate a SyllabusV1 from a ConceptGraphV1.

    Args:
        graph:            Input concept graph.
        mode:             'essence' | 'curriculum' | 'topic'.
        topic:            Required when mode='topic'.
        work_description: Human-readable description for prompts.
        key_terms:        Optional list of key terms for curriculum hints.
        enrichment:       Optional enrichment dict from the research pipeline.
        model:            Ollama model name.

    Returns:
        (SyllabusV1, thinking_log_entries)
    """
    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    llm = ChatOllama(model=model, temperature=0.3, num_ctx=num_ctx, format="json")

    work_description = work_description or graph.subject
    key_terms = key_terms or []

    concept_graph_json = json.dumps(graph.to_legacy_dict(), ensure_ascii=False, indent=2)
    if len(concept_graph_json) > 15000:
        concept_graph_json = concept_graph_json[:15000] + "\n... (truncated)"

    enrichment_block = ""
    if enrichment and enrichment.get("enrichment_summary"):
        enrichment_block = (
            "\n\n## Background Research Context\n"
            f"{enrichment['enrichment_summary']}\n\n"
            "Use this background to design episodes that incorporate historical context "
            "and critical perspectives."
        )

    if mode == "essence":
        prompt = ESSENCE_PROMPT.format(concept_graph_json=concept_graph_json)
    elif mode == "curriculum":
        key_terms_guidance = (
            f"Key terms to consider: {', '.join(key_terms)}" if key_terms else ""
        )
        prompt = CURRICULUM_PROMPT.format(
            concept_graph_json=concept_graph_json,
            work_description=work_description,
            key_terms_guidance=key_terms_guidance,
        )
    elif mode == "topic":
        prompt = TOPIC_PROMPT.format(
            concept_graph_json=concept_graph_json,
            topic=topic or "the central argument",
            work_description=work_description,
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")

    prompt += enrichment_block

    raw_response = llm.invoke(prompt).content
    parsed: dict | None = None
    error: str | None = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {"mode": mode, "episodes": [], "meta_narrative": ""}

    # Filter episodes to only valid dicts
    if parsed and "episodes" in parsed:
        parsed["episodes"] = [ep for ep in parsed["episodes"] if isinstance(ep, dict)]

    step = create_step(
        layer="producer", node="planner",
        action=f"plan_{mode}",
        input_summary=f"mode={mode}, concepts={len(graph.concepts)}",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Generated {len(parsed.get('episodes', []))} episodes in {mode} mode",
    )

    syllabus = SyllabusV1.from_legacy_dict(parsed, subject=graph.subject)
    return syllabus, [step]
