"""Mode routing (Essence/Curriculum/Topic) and Syllabus generation."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.models import Syllabus


ESSENCE_PROMPT = """\
You are a podcast director designing a single, powerful episode about a philosophical work.

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
- cognitive_bridge: How this 17th-century idea connects to modern life — technology, AI, social media, etc. (in English)

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
progression of the original text's six Parts. Each episode should correspond roughly to \
one Part of the work, building progressively from foundational ideas to the most complex.

IMPORTANT: Write ALL output in English. Do NOT write in Japanese.

{key_terms_guidance}

Episode structure (follow this progression):
- Episode 1: The crisis of knowledge — why existing learning fails (Part I themes)
- Episode 2: The method discovered — the four rules and their power (Part II themes)
- Episode 3: Living while doubting — provisional morality and practical wisdom (Part III themes)
- Episode 4: The breakthrough — Cogito, God, and the foundation of certainty (Part IV themes)
- Episode 5: The machine universe — physics, biology, and the animal-machine (Part V themes)
- Episode 6: Science and society — publishing, experiments, and mastering nature (Part VI themes)

Guidelines for each episode:
- Focus on 2-4 concepts and 1-2 aporias from the concept graph
- Every episode needs a strong cliffhanger that motivates the next episode
- Cognitive bridges should be specific and modern (AI, social media, startups, bioethics, etc.)
- Each episode must connect back to the overall narrative arc

CONCEPT GRAPH:
{concept_graph_json}

For each episode, design:
- title: A compelling English title that captures the episode's essence
- theme: The central tension explored in this episode (in English)
- concept_ids: Which concept IDs this episode covers (must match IDs from the concept graph)
- aporia_ids: Which aporia IDs this episode engages with (must match IDs from the concept graph)
- cliffhanger: A question that makes listeners need the next episode (in English)
- cognitive_bridge: How this idea connects to modern life (in English)

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
- title: A compelling English title that captures the episode's essence
- theme: The central tension explored (in English)
- concept_ids: Relevant concept IDs for this topic (must match IDs from the concept graph)
- aporia_ids: Relevant aporia IDs (must match IDs from the concept graph)
- cliffhanger: A thought-provoking question (in English)
- cognitive_bridge: Modern relevance of this topic (in English)

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


def plan(state: dict) -> dict:
    """LangGraph node: generate a Syllabus based on mode."""
    mode = state["mode"]
    concept_graph = state["concept_graph"]
    topic = state.get("topic")
    steps = list(state.get("thinking_log", []))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.3, num_ctx=16384, format="json")

    book_config = state.get("book_config", {})
    book = book_config.get("book", {})
    pf = book_config.get("prompt_fragments", {})
    ctx = book_config.get("context", {})

    work_description = pf.get(
        "work_description",
        f'{book.get("author", "the author")}\'s "{book.get("title", state.get("book_title", "this work"))}"'
    )

    key_terms = ctx.get("key_terms", [])
    if key_terms:
        key_terms_guidance = f"Key terms and concepts to consider: {', '.join(key_terms)}"
    else:
        key_terms_guidance = ""

    concept_graph_json = json.dumps(concept_graph, ensure_ascii=False, indent=2)
    if len(concept_graph_json) > 15000:
        concept_graph_json = concept_graph_json[:15000] + "\n... (truncated)"

    # Enrichment context (if available from research pipeline)
    enrichment = state.get("enrichment", {})
    enrichment_summary = enrichment.get("enrichment_summary", "")
    if enrichment_summary:
        enrichment_block = (
            "\n\n## Background Research Context\n"
            f"{enrichment_summary}\n\n"
            "Use this background to design episodes that incorporate historical context "
            "and critical perspectives. Each episode should include at least one reference "
            "to the work's historical reception or a notable criticism."
        )
    else:
        enrichment_block = ""

    if mode == "essence":
        prompt = ESSENCE_PROMPT.format(concept_graph_json=concept_graph_json)
        prompt += enrichment_block
    elif mode == "curriculum":
        prompt = CURRICULUM_PROMPT.format(
            concept_graph_json=concept_graph_json,
            work_description=work_description,
            key_terms_guidance=key_terms_guidance,
        )
        prompt += enrichment_block
    elif mode == "topic":
        prompt = TOPIC_PROMPT.format(
            concept_graph_json=concept_graph_json,
            topic=topic or "methodical doubt",
            work_description=work_description,
        )
        prompt += enrichment_block
    else:
        raise ValueError(f"Unknown mode: {mode}")

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
        Syllabus(**parsed)
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = parsed or {
            "mode": mode,
            "episodes": [],
            "meta_narrative": "",
        }
    except Exception as e:
        error = f"Validation error: {e}"

    # Filter episodes to only valid dicts
    if parsed and "episodes" in parsed:
        parsed["episodes"] = [
            ep for ep in parsed["episodes"] if isinstance(ep, dict)
        ]

    steps.append(create_step(
        layer="director",
        node="planner",
        action=f"plan_{mode}",
        input_summary=f"Mode={mode}, concepts={len(concept_graph.get('concepts', []))}",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Generated {len(parsed.get('episodes', []))} episodes in {mode} mode",
    ))

    return {
        "syllabus": parsed,
        "thinking_log": steps,
    }
