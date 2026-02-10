"""Load and summarize reference files (.md, .txt) for research context."""

from pathlib import Path

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json


SUMMARIZE_PROMPT = """\
You are a research assistant summarizing a reference document about the philosophical work \
"{book_title}" by {author}.

Read the following reference text and produce a structured summary covering:
1. **Author biography** — key facts about the author's life relevant to this work
2. **Historical context** — the era, intellectual climate, and events surrounding the work
3. **Publication history** — how the work was published, received, and disseminated
4. **Key arguments** — the main philosophical claims and their structure
5. **Critical reception** — how other thinkers responded to this work
6. **Modern significance** — why this work matters today

Be thorough but concise. Focus on facts that would be useful for creating an engaging \
podcast discussion about this work.

Respond ONLY with valid JSON:
{{
  "author_biography": "...",
  "historical_context": "...",
  "publication_history": "...",
  "key_arguments": "...",
  "critical_reception": "...",
  "modern_significance": "..."
}}

REFERENCE TEXT:
{text}
"""


def load_reference_files(file_paths: list[str]) -> list[dict]:
    """Load reference files and return their contents.

    Returns list of dicts with: path, filename, content.
    Missing files are skipped with a warning.
    """
    loaded = []
    for fp in file_paths:
        path = Path(fp)
        if not path.exists():
            print(f"      [reference_loader] File not found, skipping: {fp}")
            continue

        content = path.read_text(encoding="utf-8")
        loaded.append({
            "path": str(path),
            "filename": path.name,
            "content": content,
        })

    return loaded


def summarize_reference(content: str, book_title: str, author: str,
                        llm: ChatOllama) -> tuple[dict, dict]:
    """Summarize a single reference document using LLM.

    Returns (summary_dict, step_log_dict).
    """
    import json

    # Truncate if very long to fit context window
    text = content[:30000]

    prompt = SUMMARIZE_PROMPT.format(
        book_title=book_title,
        author=author,
        text=text,
    )

    raw_response = llm.invoke(prompt).content

    parsed = None
    error = None
    try:
        parsed = extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        error = f"JSON parse error: {e}"
        parsed = {"raw_summary": raw_response[:2000]}

    step = create_step(
        layer="researcher",
        node="reference_loader",
        action="summarize_reference",
        input_summary=f"Summarizing reference ({len(content)} chars)",
        llm_prompt=prompt,
        llm_raw_response=raw_response,
        parsed_output=parsed,
        error=error,
        reasoning=f"Generated structured summary of reference document",
    )

    return parsed, step
