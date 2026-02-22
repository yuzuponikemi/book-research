"""Research orchestrator: combines web search + reference files into structured context."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.researcher.web_search import search_batch, format_search_results
from src.researcher.reference_loader import load_reference_files, summarize_reference


INTEGRATION_PROMPT = """\
You are a research assistant integrating multiple sources of information about \
"{book_title}" by {author} ({year}).

Your task: Synthesize the web search results and reference summaries below into a \
single, coherent research context document. Organize the information into clear categories.

WEB SEARCH RESULTS:
{web_results_text}

REFERENCE FILE SUMMARIES:
{reference_summaries_text}

Produce a structured research context covering:
1. **author_biography**: Key facts about {author}'s life, education, travels, and intellectual development
2. **historical_context**: The era, intellectual climate, scientific developments, and political events
3. **publication_history**: How "{book_title}" came to be written and published, its original reception
4. **critical_reception**: How the work was received across centuries — supporters, critics, influence
5. **modern_significance**: Why this work matters today, its relevance to contemporary issues

Be factual and detailed. Cite specific names, dates, and events where possible.

Respond ONLY with valid JSON:
{{
  "author_biography": "...",
  "historical_context": "...",
  "publication_history": "...",
  "critical_reception": "...",
  "modern_significance": "..."
}}
"""


def research(state: dict) -> dict:
    """Pipeline function: gather and synthesize research context.

    Combines web search results and reference file summaries into a
    structured research_context dict.

    Args:
        state: Pipeline state with book_config, reader_model.

    Returns:
        Dict with research_context, web_sources, reference_summaries,
        and updated thinking_log.
    """
    book_config = state.get("book_config", {})
    steps = list(state.get("thinking_log", []))

    book = book_config.get("book", {})
    book_title = book.get("title", state.get("book_title", ""))
    author = book.get("author", "")
    year = str(book.get("year", ""))

    research_config = book_config.get("research", {})
    model = state.get("reader_model", "llama3")

    # ── Step 1: Web search ──────────────────────────────────────
    queries = research_config.get("search_queries", [])
    max_results = research_config.get("max_search_results", 5)

    print(f"      Searching web ({len(queries)} queries)...")
    web_results = search_batch(queries, max_results=max_results)

    steps.append(create_step(
        layer="researcher",
        node="web_search",
        action="search_batch",
        input_summary=f"{len(queries)} queries, max {max_results} results each",
        parsed_output={"result_count": len(web_results)},
        reasoning=f"Web search returned {len(web_results)} results across {len(queries)} queries",
    ))

    # ── Step 2: Load and summarize reference files ──────────────
    ref_paths = research_config.get("reference_files", [])
    reference_summaries = []

    if ref_paths:
        print(f"      Loading {len(ref_paths)} reference file(s)...")
        ref_files = load_reference_files(ref_paths)

        llm = ChatOllama(model=model, temperature=0.1, num_ctx=32768, format="json")

        for ref in ref_files:
            print(f"      Summarizing {ref['filename']}...", end="", flush=True)
            summary, step = summarize_reference(
                content=ref["content"],
                book_title=book_title,
                author=author,
                llm=llm,
            )
            reference_summaries.append({
                "filename": ref["filename"],
                "summary": summary,
            })
            steps.append(step)
            print(" done")

    # ── Step 3: Integrate into unified research context ─────────
    print("      Integrating research context...")

    web_results_text = format_search_results(web_results)
    if len(web_results_text) > 10000:
        web_results_text = web_results_text[:10000] + "\n... (truncated)"

    if reference_summaries:
        ref_text_parts = []
        for rs in reference_summaries:
            ref_text_parts.append(f"### {rs['filename']}")
            ref_text_parts.append(json.dumps(rs["summary"], ensure_ascii=False, indent=2))
        reference_summaries_text = "\n\n".join(ref_text_parts)
    else:
        reference_summaries_text = "(No reference files available)"

    if len(reference_summaries_text) > 10000:
        reference_summaries_text = reference_summaries_text[:10000] + "\n... (truncated)"

    llm = ChatOllama(model=model, temperature=0.1, num_ctx=32768, format="json")

    prompt = INTEGRATION_PROMPT.format(
        book_title=book_title,
        author=author,
        year=year,
        web_results_text=web_results_text,
        reference_summaries_text=reference_summaries_text,
    )

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {
            "author_biography": "",
            "historical_context": "",
            "publication_history": "",
            "critical_reception": "",
            "modern_significance": "",
        }

    # Attach source metadata
    parsed["web_sources"] = [
        {"title": r["title"], "url": r["url"]} for r in web_results
    ]
    parsed["reference_files"] = [rs["filename"] for rs in reference_summaries]

    steps.append(create_step(
        layer="researcher",
        node="researcher",
        action="integrate_context",
        input_summary=f"Integrating {len(web_results)} web results + {len(reference_summaries)} references",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Produced unified research context from {len(web_results)} web results "
                  f"and {len(reference_summaries)} reference files",
    ))

    return {
        "research_context": parsed,
        "thinking_log": steps,
    }


def format_research_context(ctx: dict) -> str:
    """Create a human-readable research context report."""
    lines = ["# Research Context", ""]

    fields = [
        ("Author Biography", "author_biography"),
        ("Historical Context", "historical_context"),
        ("Publication History", "publication_history"),
        ("Critical Reception", "critical_reception"),
        ("Modern Significance", "modern_significance"),
    ]

    for heading, key in fields:
        value = ctx.get(key, "")
        if value:
            lines.append(f"## {heading}")
            lines.append(str(value) if not isinstance(value, str) else value)
            lines.append("")

    web_sources = ctx.get("web_sources", [])
    if web_sources:
        lines.append("## Web Sources")
        for s in web_sources:
            lines.append(f"- [{s.get('title', '?')}]({s.get('url', '')})")
        lines.append("")

    ref_files = ctx.get("reference_files", [])
    if ref_files:
        lines.append("## Reference Files")
        for f in ref_files:
            lines.append(f"- {f}")
        lines.append("")

    return "\n".join(lines)
