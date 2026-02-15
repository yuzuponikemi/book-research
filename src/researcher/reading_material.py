"""Generate a detailed reading material document from pipeline data.

Produces a comprehensive, Gemini Deep Research-style document that serves
as a companion reading to the podcast scripts. The document covers:
- Abstract / overview
- Historical and biographical context
- Part-by-part detailed analysis with argument structures
- Critical perspectives and reception history
- Modern significance and conclusions

The output aims for ~3000-5000 words (10,000-15,000 chars in Japanese).
"""

import json
import re

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json


# ── Section generation prompts ───────────────────────────────────────

ABSTRACT_PROMPT = """\
You are an academic writer creating a comprehensive study guide for \
"{book_title}" by {author} ({year}).

Based on the following source material, write a detailed ABSTRACT (400-600 words) \
that covers:
1. What this work is about and why it was written — include the historical and \
intellectual context in which the work was produced
2. The main arguments and contributions — the key concepts, frameworks, or theories \
the author introduces
3. Its historical significance and lasting impact on its field
4. Why it remains relevant today — connections to current debates, technologies, or \
social challenges

SOURCE MATERIAL:
{enrichment_summary}

IMPORTANT: Base your abstract SOLELY on the source material above. Do NOT introduce \
information about other works or authors not mentioned in the source material.

Write the abstract in Japanese (日本語). Use an academic but accessible tone.
The abstract should give the reader a complete overview of the work's significance.
Do NOT start with a heading — write ONLY the abstract body text.

Respond with ONLY the abstract text, no JSON wrapping, no markdown headings.
"""

CHAPTER_ANALYSIS_PROMPT = """\
You are an academic writer creating a detailed chapter-by-chapter analysis of \
"{book_title}" by {author}.

Below are the analysis results for one section of the text. Write a detailed \
analytical essay (600-1000 words in Japanese) for this section. Structure it with \
these subsections using ## level headings:

## 概要
What happens in this section, what {author} argues

## 主要概念
Explain the 3-5 most important concepts and ideas introduced (use bold for terms)

## 論証構造の分析
Break down the logical structure of the arguments — premises, conclusions, argument types

## 修辞的技法
Note any metaphors, analogies, thought experiments, or rhetorical devices and their function in the argument

## 批判的考察
Discuss specific criticisms or counter-arguments relevant to concepts in this section. \
Use ONLY the critical perspectives provided below — do NOT invent critics or criticisms.
{critics_instruction}

SECTION: {section_label}

CHUNK TEXT (first 2000 chars):
{chunk_preview}

ANALYSIS DATA:
Concepts: {concepts_text}
Arguments: {arguments_text}
Rhetorical Strategies: {rhetorical_text}
Logic Flow: {logic_flow}

{critique_context}

Write in Japanese (日本語). Use an academic but accessible tone with specific references \
to the text. Include relevant quotes where the analysis data provides them.
Do NOT add a top-level heading (# ...) — start directly with the ## 概要 subsection.

Respond with ONLY the essay text, no JSON wrapping.
"""

CONCLUSION_PROMPT = """\
You are an academic writer creating the conclusion chapter for a comprehensive \
study guide on "{book_title}" by {author} ({year}).

Based on the following material, write a conclusion chapter (600-1000 words in Japanese) \
that covers:

1. **{author}の貢献**: この著作がもたらした根本的な変化や革新 — その分野における位置づけ

2. **批判的受容**: 具体的な批評家や対立する立場に言及すること。\
以下の批評家リストを参考にすること: {critics_list}

3. **現代的意義**: なぜこの著作は今日でも重要か? 現在の議論、テクノロジー、社会的課題との\
接点について論じること

4. **結語**: この著作の永続的価値についての考察

IMPORTANT: Base your conclusion SOLELY on the material provided below. Do NOT introduce \
information about other works, authors, or concepts not present in the source material.

ENRICHMENT CONTEXT:
{enrichment_summary}

CRITIQUE PERSPECTIVES:
{critique_perspectives}

OVERARCHING DEBATES:
{debates_text}

Write in Japanese (日本語). Use an academic but accessible tone.
Do NOT add a top-level heading (# ...) — start directly with the content.

Respond with ONLY the essay text, no JSON wrapping, no top-level heading.
"""


def _strip_leading_headings(text: str) -> str:
    """Remove any leading top-level markdown headings (# ...) from LLM output."""
    lines = text.split("\n")
    result = []
    found_content = False
    for line in lines:
        # Skip leading # headings (but keep ## and deeper)
        if not found_content and re.match(r'^#\s+', line) and not re.match(r'^##', line):
            continue
        found_content = True
        result.append(line)
    return "\n".join(result).strip()


def _deduplicate_sources(web_sources: list[dict]) -> list[dict]:
    """Remove duplicate web sources by URL."""
    seen_urls = set()
    unique = []
    for ws in web_sources:
        url = ws.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(ws)
    return unique


def generate_reading_material(state: dict) -> dict:
    """Pipeline function: generate comprehensive reading material.

    Uses concept_graph, chunk_analyses, research_context, critique_report,
    and enrichment to produce a detailed study guide document.

    Args:
        state: Pipeline state with all previous stage outputs.

    Returns:
        Dict with reading_material (str) and updated thinking_log.
    """
    book_config = state.get("book_config", {})
    steps = list(state.get("thinking_log", []))

    book = book_config.get("book", {})
    book_title = book.get("title", state.get("book_title", ""))
    book_title_ja = book.get("title_ja", book_title)
    author = book.get("author", "")
    author_ja = book.get("author_ja", author)
    year = str(book.get("year", ""))

    model = state.get("reader_model", "llama3")
    llm = ChatOllama(model=model, temperature=0.3, num_ctx=32768)

    enrichment = state.get("enrichment", {})
    enrichment_summary = enrichment.get("enrichment_summary", "")
    enrichment_summary_ja = enrichment.get("enrichment_summary_ja", "")
    critique_perspectives_ja = enrichment.get("critique_perspectives_ja", "")

    critique_report = state.get("critique_report", {})
    chunk_analyses = state.get("chunk_analyses", [])
    raw_chunks = state.get("raw_chunks", [])
    concept_graph = state.get("concept_graph", {})

    context_config = book_config.get("context", {})
    notable_critics = context_config.get("notable_critics", [])
    critics_list = ", ".join(c.get("name", "") for c in notable_critics) or "various scholars"

    sections = []

    # ── 1. Title and Abstract ────────────────────────────────────────
    print("      Generating abstract...")

    # Use Japanese enrichment if available, fall back to English
    summary_for_abstract = enrichment_summary_ja or enrichment_summary
    if not summary_for_abstract:
        summary_for_abstract = concept_graph.get("logic_flow", "")

    prompt = ABSTRACT_PROMPT.format(
        book_title=book_title,
        author=author,
        year=year,
        enrichment_summary=summary_for_abstract,
    )

    abstract_text = _strip_leading_headings(llm.invoke(prompt).content.strip())

    steps.append(create_step(
        layer="researcher",
        node="reading_material",
        action="generate_abstract",
        input_summary=f"Enrichment summary ({len(summary_for_abstract)} chars)",
        llm_prompt=prompt,
        llm_raw_response=abstract_text,
        parsed_output={"length": len(abstract_text)},
    ))

    title_line = (
        f"{author_ja}『{book_title_ja}』に関する包括的構造分析"
    )
    sections.append(f"# {title_line}")
    sections.append("")
    sections.append("## アブストラクト")
    sections.append(abstract_text)
    sections.append("")

    # ── 2. Chapter-by-chapter analysis ───────────────────────────────
    critique_by_concept = {}
    for crit in critique_report.get("critiques", []):
        cid = crit.get("concept_id", "")
        if cid:
            critique_by_concept[cid] = crit

    for i, (chunk, analysis) in enumerate(zip(raw_chunks, chunk_analyses)):
        section_num = i + 1
        first_line = chunk.strip().split("\n")[0]
        section_label = f"Section {section_num}: {first_line[:80]}"

        print(f"      Generating analysis for section {section_num}/{len(raw_chunks)}...")

        # Build concepts text
        concepts = analysis.get("concepts", [])
        concepts_text = "\n".join(
            f"- {c.get('name', '?')}: {c.get('description', '')[:200]}"
            for c in concepts
        ) or "(none extracted)"

        # Build arguments text
        arguments = analysis.get("arguments", [])
        arguments_parts = []
        for arg in arguments:
            premises = "; ".join(arg.get("premises", []))
            arguments_parts.append(
                f"- [{arg.get('argument_type', '?')}] "
                f"Premises: {premises[:200]} → Conclusion: {arg.get('conclusion', '')[:200]}"
            )
        arguments_text = "\n".join(arguments_parts) or "(none extracted)"

        # Build rhetorical text
        rhetorical = analysis.get("rhetorical_strategies", [])
        rhetorical_text = "\n".join(
            f"- {r.get('strategy_type', '?')}: {r.get('description', '')[:200]}"
            for r in rhetorical
        ) or "(none extracted)"

        logic_flow = analysis.get("logic_flow", "")

        # Gather critique context from critique_report for concepts in this chunk
        critique_parts = []
        for c in concepts:
            cid = c.get("id", "")
            if cid in critique_by_concept:
                crit = critique_by_concept[cid]
                for hc in crit.get("historical_criticisms", []):
                    if isinstance(hc, dict):
                        critique_parts.append(
                            f"- {hc.get('critic', '?')}: {hc.get('criticism', '')[:200]}"
                        )
                    elif isinstance(hc, str):
                        critique_parts.append(f"- {hc[:200]}")

        critique_context = ""
        if critique_parts:
            critique_context = (
                "CRITICAL PERSPECTIVES from historical analysis:\n"
                + "\n".join(critique_parts[:6])
            )

        # Build critic instructions from book config notable_critics + critique data
        critics_instruction_parts = []
        if critique_parts:
            critics_instruction_parts.append(
                "以下の批判的視点を参考にすること:\n" + "\n".join(critique_parts[:6])
            )
        if notable_critics:
            nc_lines = [
                f"- **{c.get('name', '?')}**: {c.get('perspective', '')}"
                for c in notable_critics
            ]
            critics_instruction_parts.append(
                "以下の批評家の視点も参照可能:\n" + "\n".join(nc_lines)
            )
        critics_instruction = "\n".join(critics_instruction_parts) if critics_instruction_parts else \
            "この章に関連する批判的視点があれば言及すること。"

        prompt = CHAPTER_ANALYSIS_PROMPT.format(
            book_title=book_title,
            author=author,
            section_label=section_label,
            chunk_preview=chunk[:2000],
            concepts_text=concepts_text,
            arguments_text=arguments_text,
            rhetorical_text=rhetorical_text,
            logic_flow=logic_flow[:500],
            critique_context=critique_context,
            critics_instruction=critics_instruction,
        )

        chapter_text = _strip_leading_headings(llm.invoke(prompt).content.strip())

        steps.append(create_step(
            layer="researcher",
            node="reading_material",
            action=f"generate_chapter_{section_num}",
            input_summary=f"Section {section_num}: {len(concepts)} concepts, {len(arguments)} arguments",
            llm_prompt=prompt,
            llm_raw_response=chapter_text,
            parsed_output={"length": len(chapter_text)},
        ))

        sections.append(f"## 第{section_num}章の詳細分析 —— {first_line[:60]}")
        sections.append(chapter_text)
        sections.append("")

    # ── 3. Conclusion chapter ────────────────────────────────────────
    print("      Generating conclusion...")

    debates = critique_report.get("overarching_debates", [])
    debates_text = "\n".join(
        f"- {d}" if isinstance(d, str) else f"- {d.get('debate', str(d)[:200])}"
        for d in debates
    ) or "(none)"

    prompt = CONCLUSION_PROMPT.format(
        book_title=book_title,
        author=author,
        year=year,
        critics_list=critics_list,
        enrichment_summary=enrichment_summary_ja or enrichment_summary,
        critique_perspectives=critique_perspectives_ja or "(not available)",
        debates_text=debates_text,
    )

    conclusion_text = _strip_leading_headings(llm.invoke(prompt).content.strip())

    steps.append(create_step(
        layer="researcher",
        node="reading_material",
        action="generate_conclusion",
        input_summary=f"Critics: {critics_list}, {len(debates)} debates",
        llm_prompt=prompt,
        llm_raw_response=conclusion_text,
        parsed_output={"length": len(conclusion_text)},
    ))

    sections.append("## 総合的結論および後世への影響")
    sections.append(conclusion_text)
    sections.append("")

    # ── 4. Sources section (deduplicated) ─────────────────────────────
    research_context = state.get("research_context", {})
    web_sources = _deduplicate_sources(research_context.get("web_sources", []))
    ref_files = research_context.get("reference_files", [])

    if web_sources or ref_files:
        sections.append("## 参考文献")
        for ws in web_sources:
            title = ws.get("title", "?")
            url = ws.get("url", "")
            sections.append(f"- [{title}]({url})")
        for rf in ref_files:
            sections.append(f"- {rf}")
        sections.append("")

    reading_material = "\n".join(sections)

    return {
        "reading_material": reading_material,
        "thinking_log": steps,
    }
