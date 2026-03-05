"""WebResearcher — Step 3: aggregate search results per heading.

For each heading, an LLM synthesises all web search snippets into a single
coherent summary paragraph. This "synthetic chunk" is the web-research
equivalent of a book chapter's text.

Output: list[SynthesizedChunk]  (ready to feed into synthesizer.py)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import time

from langchain_ollama import ChatOllama

from cogito.utils import event_log

from cogito.utils.logger import create_step, extract_json
from cogito.services.web_researcher.planner import Heading
from cogito.services.web_researcher.searcher import SearchResult


@dataclass
class SynthesizedChunk:
    """The web-research equivalent of a book chapter chunk."""

    heading_id: str
    heading_title: str
    summary_text: str            # LLM-synthesised prose — feeds into Analyst's extractor
    sources: list[str] = field(default_factory=list)  # URLs


AGGREGATION_PROMPT = """\
You are a scholarly research assistant synthesizing web search results.

Subject: {subject}
Section: "{heading_title}"
Description: {heading_description}

Below are web search results related to this section:

{search_results_text}

Your task: Write a detailed, scholarly summary paragraph (400-700 words) covering this
section of the subject. The paragraph should:
- Synthesize ALL relevant information from the search results above
- Focus on key concepts, ideas, arguments, and their significance
- Include specific facts, dates, names, and quotes where available
- Be written in a neutral, analytical tone suitable for academic discourse
- Connect the ideas to the broader subject where relevant

Write the summary in English. Be thorough and specific — this will be used for
deep philosophical/conceptual analysis.

Respond ONLY with valid JSON:
{{
  "summary": "..."
}}
"""


def _format_results_for_prompt(results: list[SearchResult], max_chars: int = 8000) -> str:
    lines = []
    total = 0
    for r in results:
        entry = f"**{r.title}** ({r.url})\n{r.body}"
        if total + len(entry) > max_chars:
            break
        lines.append(entry)
        total += len(entry)
    return "\n\n---\n\n".join(lines) if lines else "(No search results)"


def aggregate_headings(
    headings: list[Heading],
    results_by_heading: dict[str, list[SearchResult]],
    subject: str,
    model: str = "llama3",
) -> tuple[list[SynthesizedChunk], list[dict]]:
    """Aggregate search results into a SynthesizedChunk per heading.

    Args:
        headings:            Ordered list of headings from planner.
        results_by_heading:  Search results keyed by heading.id (from searcher).
        subject:             Full subject description.
        model:               Ollama model for aggregation.

    Returns:
        (list[SynthesizedChunk], thinking_log_entries)
    """
    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=num_ctx, format="json")

    chunks: list[SynthesizedChunk] = []
    log: list[dict] = []

    for heading in headings:
        results = results_by_heading.get(heading.id, [])
        print(f"      [aggregator] Summarising '{heading.title}' ({len(results)} results)...",
              end="", flush=True)

        search_results_text = _format_results_for_prompt(results)
        prompt = AGGREGATION_PROMPT.format(
            subject=subject,
            heading_title=heading.title,
            heading_description=heading.description or heading.title,
            search_results_text=search_results_text,
        )

        _t0 = time.time()
        raw_response = llm.invoke(prompt).content
        event_log.llm("web_researcher/aggregator", f"summarize: {heading.title[:30]}", model, time.time() - _t0)
        parsed: dict | None = None
        error: str | None = None
        try:
            parsed = extract_json(raw_response)
            summary = parsed.get("summary", "")
        except (json.JSONDecodeError, ValueError) as e:
            error = f"JSON parse error: {e}"
            summary = raw_response[:1000]

        sources = list({r.url for r in results if r.url})
        chunk = SynthesizedChunk(
            heading_id=heading.id,
            heading_title=heading.title,
            summary_text=summary,
            sources=sources,
        )
        chunks.append(chunk)
        print(f" {len(summary)} chars", flush=True)

        log.append(create_step(
            layer="web_researcher", node="aggregator",
            action=f"aggregate:{heading.id}",
            input_summary=f"heading='{heading.title}', {len(results)} web results",
            llm_prompt=prompt,
            llm_raw_response=raw_response,
            parsed_output={"summary_length": len(summary), "sources": sources[:3]},
            error=error,
            reasoning=f"Synthesised {len(results)} results → {len(summary)} char summary",
        ))

    return chunks, log
