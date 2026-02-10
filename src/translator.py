"""Translate English intermediate outputs to Japanese using TranslateGemma."""

import re
import time

from langchain_ollama import ChatOllama


TRANSLATE_PROMPT = """\
You are a professional English (en) to Japanese (ja) translator. \
Your goal is to accurately convey the meaning and nuances of the original \
English text while adhering to Japanese grammar, vocabulary, and cultural \
sensitivities. This text is about {work_description}. \
Preserve all technical philosophical terms accurately. Keep markdown \
formatting (headers, bold, lists, quotes) intact.
Produce only the Japanese translation, without any additional explanations \
or commentary. Please translate the following English text into Japanese:


{{text}}"""

# Maximum characters per translation chunk to avoid context overflow.
# TranslateGemma 12B has limited context; we split long texts.
MAX_CHUNK_CHARS = 3000


def _split_by_sections(text: str) -> list[str]:
    """Split markdown text into sections (by ## headers) for chunked translation.

    Each section is kept as a whole unit if possible.
    Sections exceeding MAX_CHUNK_CHARS are further split by paragraphs.
    """
    # Split by level-2 or level-3 headers
    parts = re.split(r'(^#{2,3} .+$)', text, flags=re.MULTILINE)

    sections = []
    current = ""
    for part in parts:
        if re.match(r'^#{2,3} ', part):
            if current.strip():
                sections.append(current)
            current = part
        else:
            current += part

    if current.strip():
        sections.append(current)

    # Further split oversized sections by paragraphs
    result = []
    for section in sections:
        if len(section) <= MAX_CHUNK_CHARS:
            result.append(section)
        else:
            paragraphs = section.split("\n\n")
            chunk = ""
            for para in paragraphs:
                if len(chunk) + len(para) > MAX_CHUNK_CHARS and chunk:
                    result.append(chunk)
                    chunk = para
                else:
                    chunk = chunk + "\n\n" + para if chunk else para
            if chunk:
                result.append(chunk)

    return result


def translate_text(text: str, model: str = "translategemma:12b",
                   work_description: str = "") -> str:
    """Translate a full markdown document from English to Japanese.

    Splits into sections, translates each, and reassembles.
    """
    llm = ChatOllama(model=model, temperature=0.1, num_ctx=8192)

    # Build the prompt template with work_description baked in
    prompt_template = TRANSLATE_PROMPT.format(
        work_description=work_description or "a philosophical work",
    )

    sections = _split_by_sections(text)
    translated_parts = []

    for i, section in enumerate(sections):
        # Skip empty sections or sections that are already mostly Japanese
        if not section.strip():
            translated_parts.append(section)
            continue

        prompt = prompt_template.format(text=section)
        try:
            result = llm.invoke(prompt).content
            translated_parts.append(result)
        except Exception as e:
            # On error, keep original with a note
            translated_parts.append(f"<!-- 翻訳エラー: {e} -->\n{section}")

        if (i + 1) % 5 == 0:
            print(f"        [{i+1}/{len(sections)}] sections translated...")

    return "\n\n".join(translated_parts)


def translate_intermediate_outputs(
    run_dir: "Path",
    model: str = "translategemma:12b",
    work_description: str = "",
) -> list[str]:
    """Translate all English intermediate .md files to Japanese _ja.md versions.

    Translates:
    - 02_chunk_analyses.md -> 02_chunk_analyses_ja.md
    - 03_concept_graph.md -> 03_concept_graph_ja.md
    - 04_syllabus.md -> 04_syllabus_ja.md

    Returns list of saved file paths.
    """
    from pathlib import Path
    run_dir = Path(run_dir)

    targets = [
        ("02_chunk_analyses.md", "02_chunk_analyses_ja.md", "チャンク分析レポート"),
        ("03_concept_graph.md", "03_concept_graph_ja.md", "統合コンセプトグラフ"),
        ("04_syllabus.md", "04_syllabus_ja.md", "シラバス"),
    ]

    saved = []
    for src_name, dst_name, label in targets:
        src_path = run_dir / src_name
        dst_path = run_dir / dst_name

        if not src_path.exists():
            print(f"      Skipping {src_name} (not found)")
            continue

        text = src_path.read_text(encoding="utf-8")
        print(f"      Translating {src_name} -> {dst_name} ({label})...")
        t0 = time.time()

        translated = translate_text(text, model=model, work_description=work_description)

        elapsed = time.time() - t0
        dst_path.write_text(translated, encoding="utf-8")
        print(f"      -> {dst_name} saved ({elapsed:.1f}s)")
        saved.append(str(dst_path))

    return saved
