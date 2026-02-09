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

CONCEPT GRAPH:
{concept_graph_json}

Design one episode with:
- title: A compelling Japanese title
- theme: The central tension explored
- concept_ids: The 2-3 most important concept IDs
- aporia_ids: The 1-2 most important aporia IDs
- cliffhanger: A thought-provoking question to leave listeners with
- cognitive_bridge: How this 17th-century idea connects to modern life (technology, AI, social media, etc.)

Also provide:
- meta_narrative: A one-sentence description of the overall story arc

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
You are a podcast director designing a multi-episode curriculum about a philosophical work.

Given the concept graph below, create a 3-5 episode series that follows the logical \
progression of ideas. Use the concept dependencies to determine episode order—each \
episode should build on the previous one.

CONCEPT GRAPH:
{concept_graph_json}

For each episode, design:
- title: A compelling Japanese title
- theme: The central tension explored in this episode
- concept_ids: Which concepts this episode covers
- aporia_ids: Which aporias this episode engages with
- cliffhanger: A question that makes listeners need the next episode
- cognitive_bridge: How this idea connects to modern life

Also provide:
- meta_narrative: The overarching story told across all episodes

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
You are a podcast director designing a focused episode about a specific topic within a \
philosophical work.

Given the concept graph and the requested topic "{topic}", filter the graph to find the \
most relevant concepts and aporias. Create 1-2 episodes that deeply explore this topic.

CONCEPT GRAPH:
{concept_graph_json}

REQUESTED TOPIC: {topic}

For each episode, design:
- title: A compelling Japanese title
- theme: The central tension explored
- concept_ids: Relevant concept IDs for this topic
- aporia_ids: Relevant aporia IDs
- cliffhanger: A thought-provoking question
- cognitive_bridge: Modern relevance of this topic

Also provide:
- meta_narrative: The story arc for this topic exploration

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

    concept_graph_json = json.dumps(concept_graph, ensure_ascii=False, indent=2)
    if len(concept_graph_json) > 10000:
        concept_graph_json = concept_graph_json[:10000] + "\n... (truncated)"

    if mode == "essence":
        prompt = ESSENCE_PROMPT.format(concept_graph_json=concept_graph_json)
    elif mode == "curriculum":
        prompt = CURRICULUM_PROMPT.format(concept_graph_json=concept_graph_json)
    elif mode == "topic":
        prompt = TOPIC_PROMPT.format(
            concept_graph_json=concept_graph_json,
            topic=topic or "methodical doubt",
        )
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
