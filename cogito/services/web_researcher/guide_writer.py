"""WebResearcher — Step 5: generate a detailed book guide (Markdown).

Takes SynthesizedChunks + ConceptGraphV1 and writes a structured reading guide
with one deep-dive section per heading, plus an intro, overview table, and
practical checklist.

Output: book_guide.md  (in the same directory as 03_concept_graph.json)
"""

from __future__ import annotations

from pathlib import Path

from langchain_ollama import ChatOllama

from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.services.web_researcher.aggregator import SynthesizedChunk
from cogito.services.web_researcher.planner import Heading


# ── Prompts ───────────────────────────────────────────────────────────────────

INTRO_PROMPT = """\
あなたは哲学書の詳細なブックガイドを執筆する専門家です。

## 書籍情報
- タイトル: {book_title_ja}
- 著者: {author_ja}（{year}）
- 分野: {tradition}
- 概要: {work_description}

## 本書の論理展開（コンセプトグラフより）
{logic_flow}

## 中心的な緊張（Core Frustration）
{core_frustration}

## 章立て（全{total_sections}章）
{headings_list}

---

以下の構成でブックガイドの序論をMarkdownで執筆してください（JSONは不要）。

# {book_title_ja} ブックガイド

## 序論：{intro_subtitle}

（書き出し）現代における本書の意義と問題提起（200字程度）

（テーゼ）著者が再定義する勉強観の核心（200字程度）

## 本書の構成と学習フェーズ

（章タイトルと学習フェーズのMarkdown表。列：章番号、見出しタイトル、学習フェーズ、主なキーワード）

## このガイドの使い方

（読者へのガイダンス：100字程度）

---

Markdownのみで回答してください。タイトルは上記の # ... で始めること。
"""

SECTION_PROMPT = """\
あなたは哲学書のブックガイドを執筆する専門家です。

## 書籍
タイトル: {book_title_ja}（著者: {author_ja}）
全体テーマ: {work_description}

## 全体の論理展開（参考）
{logic_flow}

## 担当セクション
セクション番号: 第{section_num}章（全{total_sections}章中）
見出しタイトル: {heading_title}
このセクションの要点: {heading_description}

## リサーチ素材（Webから収集した情報の統合）
{summary_text}

## 関連概念・関係（コンセプトグラフより）
{related_text}

---

以下の構成でこのセクションをMarkdownで執筆してください（JSONは不要）。

## 第{section_num}章 {heading_title}

（イントロダクション：このセクションの問いと意義。150-200字）

### [著者の主張の核心を表すサブセクションタイトル]

（詳細解説。著者の主張を忠実に再現しつつ、哲学的背景・類似概念・関連思想家も補足。300-400字）

### [別の角度からの掘り下げ（例：メカニズム、危険性、実践的含意など）]

（詳細解説。具体例を2-3個含める。現代的事例も歓迎。300-400字）

### [他セクションとの接続または本セクションの小括]

（このセクションの締めくくりと、次章への橋渡し。100-150字）

**執筆要件:**
- 日本語の専門概念には英訳を（カッコ）内に付ける
- 学術的だが一般読者にも読みやすい文体
- Markdownのみで回答（JSONは不要）
- 第{section_num}章の ## 見出しで始めること
"""

CHECKLIST_PROMPT = """\
あなたは哲学書のブックガイドの実践ガイドを執筆する専門家です。

## 書籍
タイトル: {book_title_ja}（著者: {author_ja}）

## 本書の未解決の問い（アポリア）
{aporias_text}

## 主要概念
{concepts_text}

## 全体の論理展開
{logic_flow}

---

本書の読者が「変身（Transformation）」を実践するための具体的なチェックリストを
Markdownで執筆してください（JSONは不要）。

## 実践ガイド：「来たるべきバカ」になるためのチェックリスト

（概要：100字程度）

### フェーズ1：[最初のフェーズ名]（対応章：第X章）

- [ ] （具体的なアクション）
- [ ] （具体的なアクション）
- [ ] （具体的なアクション）

### フェーズ2：[次のフェーズ名]

- [ ] ...

### フェーズ3：[最終フェーズ名]

- [ ] ...

（締めくくり：本書の意義を一文で）

**要件:** 抽象的な言葉ではなく、読者が明日から実践できる具体的な行動レベルで記述すること。
Markdownのみで回答。
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _related_text_for_chunk(
    heading_id: str,
    graph: ConceptGraphV1,
) -> str:
    """Format concepts and relations related to a given heading."""
    lines: list[str] = []

    # Concepts sourced from this heading
    related_concepts = [
        c for c in graph.concepts if c.source_chunk == heading_id
    ]
    if related_concepts:
        lines.append("**このセクションの主要概念:**")
        for c in related_concepts:
            lines.append(f"- **{c.name}**: {c.description[:200]}")

    # Relations involving these concepts
    concept_ids = {c.id for c in related_concepts}
    related_rels = [
        r for r in graph.relations
        if r.source in concept_ids or r.target in concept_ids
    ]
    if related_rels:
        lines.append("\n**他の概念との関係:**")
        for r in related_rels:
            lines.append(
                f"- {r.source} →[{r.relation_type}]→ {r.target}: {r.evidence[:120]}"
            )

    return "\n".join(lines) if lines else "（このセクション固有の概念情報なし）"


def _llm(model: str) -> ChatOllama:
    return ChatOllama(model=model, temperature=0.4, num_ctx=32768)


# ── Main entry point ──────────────────────────────────────────────────────────

def write_book_guide(
    chunks: list[SynthesizedChunk],
    headings: list[Heading],
    graph: ConceptGraphV1,
    output_path: Path,
    book_config: dict | None = None,
    model: str = "qwen3-next",
) -> Path:
    """Generate a detailed book guide (Markdown) from research chunks + concept graph.

    Args:
        chunks:      SynthesizedChunks from aggregator (one per heading).
        headings:    Original Heading objects (for descriptions).
        graph:       ConceptGraphV1 for cross-section concept links.
        output_path: Where to write the Markdown file.
        book_config: Optional book config for title/author metadata.
        model:       Ollama model (default: qwen3-next for Japanese quality).

    Returns:
        Path to the written Markdown file.
    """
    llm = _llm(model)

    # ── Extract metadata ───────────────────────────────────────────────────────
    bk = (book_config or {}).get("book", {})
    pf = (book_config or {}).get("prompt_fragments", {})
    ctx = (book_config or {}).get("context", {})

    book_title_ja = bk.get("title_ja") or bk.get("title") or graph.subject
    author_ja = bk.get("author_ja") or bk.get("author") or ""
    year = str(bk.get("year") or "")
    tradition = ctx.get("tradition") or ""
    work_description = pf.get("work_description") or graph.subject
    logic_flow = graph.logic_flow or ""
    core_frustration = graph.core_frustration or ""

    heading_by_id = {h.id: h for h in headings}
    total = len(chunks)

    # ── 1. Introduction ────────────────────────────────────────────────────────
    print(f"  [guide_writer] Writing introduction ...", flush=True)
    headings_list = "\n".join(
        f"  {i+1}. {c.heading_title}"
        for i, c in enumerate(chunks)
    )
    # Derive a subtitle from core_frustration or logic_flow
    intro_subtitle = "自己破壊としての勉強――現代における「変身」の意義"

    intro_prompt = INTRO_PROMPT.format(
        book_title_ja=book_title_ja,
        author_ja=author_ja,
        year=year,
        tradition=tradition,
        work_description=work_description,
        logic_flow=logic_flow[:1500],
        core_frustration=core_frustration[:300],
        total_sections=total,
        headings_list=headings_list,
        intro_subtitle=intro_subtitle,
    )
    intro_md = llm.invoke(intro_prompt).content.strip()

    # ── 2. Sections (one per chunk) ────────────────────────────────────────────
    section_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        heading = heading_by_id.get(chunk.heading_id)
        heading_desc = heading.description if heading else chunk.heading_title
        related = _related_text_for_chunk(chunk.heading_id, graph)

        print(
            f"  [guide_writer] Writing section {i+1}/{total}: {chunk.heading_title} ...",
            flush=True,
        )
        section_prompt = SECTION_PROMPT.format(
            book_title_ja=book_title_ja,
            author_ja=author_ja,
            work_description=work_description[:400],
            logic_flow=logic_flow[:800],
            section_num=i + 1,
            total_sections=total,
            heading_title=chunk.heading_title,
            heading_description=heading_desc,
            summary_text=chunk.summary_text[:3000],
            related_text=related,
        )
        section_md = llm.invoke(section_prompt).content.strip()
        section_parts.append(section_md)

    # ── 3. Practical checklist ─────────────────────────────────────────────────
    print(f"  [guide_writer] Writing practical checklist ...", flush=True)
    aporias_text = "\n".join(
        f"- [{a.id}] {a.question}"
        for a in graph.aporias
    )
    concepts_text = "\n".join(
        f"- **{c.name}**: {c.description[:120]}"
        for c in graph.concepts
    )
    checklist_prompt = CHECKLIST_PROMPT.format(
        book_title_ja=book_title_ja,
        author_ja=author_ja,
        aporias_text=aporias_text,
        concepts_text=concepts_text,
        logic_flow=logic_flow[:800],
    )
    checklist_md = llm.invoke(checklist_prompt).content.strip()

    # ── 4. Assemble and write ──────────────────────────────────────────────────
    parts = [intro_md] + section_parts + [checklist_md]
    full_guide = "\n\n---\n\n".join(parts)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_guide, encoding="utf-8")

    total_chars = len(full_guide)
    print(
        f"  [guide_writer] → {output_path.name} written "
        f"({total_chars:,} chars, {total + 2} sections)",
        flush=True,
    )
    return output_path
