"""Critique layer: generate historical criticisms and counter-perspectives."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json


CRITIQUE_PROMPT = """\
You are a scholar producing a critique report for "{book_title}" by {author}.

You have access to the concept graph from the original text analysis, research context \
from secondary sources, and a list of notable critics.

Your task: For each major concept in the concept graph, generate:
1. **Historical criticisms** — what specific objections were raised by contemporary or later thinkers
2. **Counter-arguments** — how the author or their defenders responded
3. **Modern reinterpretations** — how the concept is understood today
4. **Unresolved controversies** — what scholars still disagree about

CONCEPT GRAPH:
{concept_graph_json}

RESEARCH CONTEXT:
{research_context}

NOTABLE CRITICS:
{notable_critics_text}

Respond ONLY with valid JSON:
{{
  "critiques": [
    {{
      "concept_id": "...",
      "concept_name": "...",
      "historical_criticisms": [
        {{"critic": "...", "criticism": "...", "era": "..."}}
      ],
      "counter_arguments": ["..."],
      "modern_reinterpretations": ["..."],
      "unresolved_controversies": ["..."]
    }}
  ],
  "overarching_debates": [
    {{
      "debate": "...",
      "positions": ["..."],
      "significance": "..."
    }}
  ],
  "reception_narrative": "A 3-5 sentence narrative of how this work was received over time"
}}
"""


def critique(state: dict) -> dict:
    """Pipeline function: generate critique report from concept graph + research context.

    Args:
        state: Pipeline state with concept_graph, research_context, book_config.

    Returns:
        Dict with critique_report and updated thinking_log.
    """
    concept_graph = state["concept_graph"]
    research_context = state.get("research_context", {})
    book_config = state.get("book_config", {})
    steps = list(state.get("thinking_log", []))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.2, num_ctx=32768, format="json")

    book = book_config.get("book", {})
    book_title = book.get("title", state.get("book_title", ""))
    author = book.get("author", "")

    # Format concept graph
    concept_graph_json = json.dumps(concept_graph, ensure_ascii=False, indent=2)
    if len(concept_graph_json) > 12000:
        concept_graph_json = concept_graph_json[:12000] + "\n... (truncated)"

    # Format research context
    if research_context:
        research_text = json.dumps(research_context, ensure_ascii=False, indent=2)
        if len(research_text) > 8000:
            research_text = research_text[:8000] + "\n... (truncated)"
    else:
        research_text = "(No research context available)"

    # Format notable critics
    notable_critics = book_config.get("context", {}).get("notable_critics", [])
    if notable_critics:
        critics_lines = []
        for c in notable_critics:
            critics_lines.append(f"- **{c['name']}**: {c['perspective']}")
        notable_critics_text = "\n".join(critics_lines)
    else:
        notable_critics_text = "(No notable critics specified in config)"

    prompt = CRITIQUE_PROMPT.format(
        book_title=book_title,
        author=author,
        concept_graph_json=concept_graph_json,
        research_context=research_text,
        notable_critics_text=notable_critics_text,
    )

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {
            "critiques": [],
            "overarching_debates": [],
            "reception_narrative": "",
        }

    steps.append(create_step(
        layer="researcher",
        node="critic",
        action="generate_critique",
        input_summary=f"Critiquing {len(concept_graph.get('concepts', []))} concepts "
                      f"with {len(notable_critics)} notable critics",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Generated {len(parsed.get('critiques', []))} concept critiques, "
                  f"{len(parsed.get('overarching_debates', []))} overarching debates",
    ))

    return {
        "critique_report": parsed,
        "thinking_log": steps,
    }


def format_critique_report(report: dict) -> str:
    """Create a human-readable critique report."""
    lines = ["# Critique Report", ""]

    if report.get("reception_narrative"):
        lines.append("## Reception Narrative")
        lines.append(report["reception_narrative"])
        lines.append("")

    critiques = report.get("critiques", [])
    if critiques:
        lines.append("## Concept Critiques")
        lines.append("")
        for crit in critiques:
            lines.append(f"### {crit.get('concept_name', crit.get('concept_id', '?'))}")
            lines.append("")

            historical = crit.get("historical_criticisms", [])
            if historical:
                lines.append("**Historical Criticisms:**")
                for h in historical:
                    if isinstance(h, dict):
                        lines.append(f"- **{h.get('critic', '?')}** ({h.get('era', '?')}): {h.get('criticism', '')}")
                    else:
                        lines.append(f"- {h}")
                lines.append("")

            counter = crit.get("counter_arguments", [])
            if counter:
                lines.append("**Counter-arguments:**")
                for c in counter:
                    lines.append(f"- {c}")
                lines.append("")

            modern = crit.get("modern_reinterpretations", [])
            if modern:
                lines.append("**Modern Reinterpretations:**")
                for m in modern:
                    lines.append(f"- {m}")
                lines.append("")

            unresolved = crit.get("unresolved_controversies", [])
            if unresolved:
                lines.append("**Unresolved Controversies:**")
                for u in unresolved:
                    lines.append(f"- {u}")
                lines.append("")

    debates = report.get("overarching_debates", [])
    if debates:
        lines.append("## Overarching Debates")
        lines.append("")
        for d in debates:
            if isinstance(d, dict):
                lines.append(f"### {d.get('debate', '?')}")
                positions = d.get("positions", [])
                for p in positions:
                    lines.append(f"- {p}")
                if d.get("significance"):
                    lines.append(f"\n*Significance:* {d['significance']}")
            else:
                lines.append(f"- {d}")
            lines.append("")

    return "\n".join(lines)
