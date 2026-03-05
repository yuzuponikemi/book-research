"""WebResearcher — Step 2: web-search per heading.

For each heading, generates 3-5 targeted search queries and runs them,
returning a dict of {heading_id: list[SearchResult]}.

Re-uses src/researcher/web_search.search_batch for the actual HTTP calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import time

from langchain_ollama import ChatOllama

from cogito.utils import event_log

from cogito.utils.logger import create_step, extract_json
from cogito.services.web_researcher.web_search import search_batch
from cogito.services.web_researcher.planner import Heading


@dataclass
class SearchResult:
    query: str
    title: str
    url: str
    body: str


QUERY_GEN_PROMPT = """\
You are a research assistant preparing web search queries.

Subject: {subject}
Heading: "{heading_title}" — {heading_description}

Generate 4 specific, focused web search queries that would find reliable information
about this heading in the context of the subject above.
Vary the angle: biographical, philosophical, historical, contemporary relevance.

Respond ONLY with valid JSON:
{{
  "queries": ["...", "...", "...", "..."]
}}
"""


def generate_queries(
    subject: str,
    heading: Heading,
    model: str = "llama3",
) -> list[str]:
    """Generate targeted search queries for a single heading."""
    llm = ChatOllama(model=model, temperature=0.3, num_ctx=8192, format="json")
    prompt = QUERY_GEN_PROMPT.format(
        subject=subject,
        heading_title=heading.title,
        heading_description=heading.description or heading.title,
    )
    try:
        _t0 = time.time()
        raw = llm.invoke(prompt).content
        event_log.llm("web_researcher/searcher", f"generate_queries: {heading.title[:30]}", model, time.time() - _t0)
        parsed = extract_json(raw)
        return parsed.get("queries", [])
    except Exception:
        # Fallback: simple keyword queries
        return [
            f"{subject} {heading.title}",
            f"{heading.title} philosophy",
        ]


def search_headings(
    headings: list[Heading],
    subject: str,
    model: str = "llama3",
    max_results_per_query: int = 4,
) -> tuple[dict[str, list[SearchResult]], list[dict]]:
    """Run web searches for each heading.

    Args:
        headings:              List of Heading objects from planner.
        subject:               Full subject description for query generation.
        model:                 Ollama model for query generation.
        max_results_per_query: Max web results per search query.

    Returns:
        (results_by_heading_id, thinking_log_entries)
    """
    results_by_heading: dict[str, list[SearchResult]] = {}
    log: list[dict] = []

    for heading in headings:
        print(f"      [searcher] {heading.title} ...", end="", flush=True)

        # Generate queries for this heading
        queries = generate_queries(subject, heading, model=model)

        # Execute searches
        raw_results = search_batch(queries, max_results=max_results_per_query)
        results = [
            SearchResult(
                query=r["query"],
                title=r["title"],
                url=r["url"],
                body=r["body"],
            )
            for r in raw_results
        ]

        results_by_heading[heading.id] = results
        print(f" {len(results)} results", flush=True)

        log.append(create_step(
            layer="web_researcher", node="searcher",
            action=f"search:{heading.id}",
            input_summary=f"heading='{heading.title}', {len(queries)} queries",
            parsed_output={
                "heading_id": heading.id,
                "queries": queries,
                "result_count": len(results),
                "sources": [r.url for r in results[:5]],
            },
            reasoning=f"Found {len(results)} results for '{heading.title}'",
        ))

    return results_by_heading, log
