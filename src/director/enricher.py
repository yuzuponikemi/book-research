"""Enricher: merge research context + critique into a concise narrative for downstream use."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json


ENRICHMENT_PROMPT = """\
You are creating a concise background briefing for a podcast scriptwriter.

Given the research context and critique report below, produce THREE summaries:

1. **enrichment_summary** (English, 800-1200 words): A detailed narrative integrating:
   - Key biographical facts about the author that illuminate the work
   - Historical context that shaped the work's creation (specific events, dates, figures)
   - How the work was received and its lasting impact across centuries
   - Major criticisms and counter-arguments (cite specific critics by name)
   - Modern relevance and reinterpretations (AI, neuroscience, environmental ethics)

2. **enrichment_summary_ja** (Japanese, 1500-2500字 minimum): The same content in \
natural Japanese. This will be injected into a Japanese podcast script prompt and a \
reading material generator. It MUST be detailed and substantial — at least 1500 characters. \
Include specific names, dates, and events in Japanese. \
Cover ALL of the following: author biography, historical context (era, events), \
publication details (year, language, reception), major criticisms (by name), \
and modern relevance. Do NOT abbreviate — write a thorough, essay-length summary.

3. **critique_perspectives_ja** (Japanese, 400-800字): A focused summary of 3-4 of the \
most interesting critical perspectives, written as talking points that podcast hosts can \
reference in dialogue. Include:
   - パスカルの批判（神の排除）
   - ヒュームの経験主義的批判
   - カントの総合的立場
   - 現代の視点（AI、環境倫理）

RESEARCH CONTEXT:
{research_context_json}

CRITIQUE REPORT:
{critique_report_json}

Respond ONLY with valid JSON:
{{
  "enrichment_summary": "...",
  "enrichment_summary_ja": "...",
  "critique_perspectives_ja": "..."
}}
"""


def enrich(state: dict) -> dict:
    """Pipeline function: merge research + critique into enrichment summaries.

    Args:
        state: Pipeline state with research_context, critique_report, reader_model.

    Returns:
        Dict with enrichment dict and updated thinking_log.
    """
    research_context = state.get("research_context", {})
    critique_report = state.get("critique_report", {})
    steps = list(state.get("thinking_log", []))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.2, num_ctx=32768, num_predict=8192, format="json")

    research_json = json.dumps(research_context, ensure_ascii=False, indent=2)
    if len(research_json) > 10000:
        research_json = research_json[:10000] + "\n... (truncated)"

    critique_json = json.dumps(critique_report, ensure_ascii=False, indent=2)
    if len(critique_json) > 10000:
        critique_json = critique_json[:10000] + "\n... (truncated)"

    prompt = ENRICHMENT_PROMPT.format(
        research_context_json=research_json,
        critique_report_json=critique_json,
    )

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {
            "enrichment_summary": "",
            "enrichment_summary_ja": "",
            "critique_perspectives_ja": "",
        }

    steps.append(create_step(
        layer="director",
        node="enricher",
        action="create_enrichment",
        input_summary="Merging research context + critique report into enrichment summaries",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Generated enrichment: EN={len(parsed.get('enrichment_summary', ''))} chars, "
                  f"JA={len(parsed.get('enrichment_summary_ja', ''))} chars",
    ))

    return {
        "enrichment": parsed,
        "thinking_log": steps,
    }


def format_enrichment_report(enrichment: dict) -> str:
    """Create a human-readable enrichment report."""
    lines = ["# Enriched Context", ""]

    if enrichment.get("enrichment_summary"):
        lines.append("## Enrichment Summary (English)")
        lines.append(enrichment["enrichment_summary"])
        lines.append("")

    if enrichment.get("enrichment_summary_ja"):
        lines.append("## 研究背景（日本語）")
        lines.append(enrichment["enrichment_summary_ja"])
        lines.append("")

    if enrichment.get("critique_perspectives_ja"):
        lines.append("## 批判的視点（日本語）")
        lines.append(enrichment["critique_perspectives_ja"])
        lines.append("")

    return "\n".join(lines)
