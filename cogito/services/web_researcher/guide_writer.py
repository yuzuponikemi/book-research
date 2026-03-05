"""WebResearcher — Step 5: generate a detailed book guide (Markdown).

Takes SynthesizedChunks + ConceptGraphV1 and writes a structured reading guide
with one deep-dive section per heading, plus an intro, overview table, and
practical checklist.

Output: book_guide.md  (in the same directory as 03_concept_graph.json)
"""

from __future__ import annotations

import time
from pathlib import Path

from langchain_ollama import ChatOllama

from cogito.utils import event_log

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

**執筆指示:**
以下の構成でブックガイドの序論をMarkdownで執筆してください。指示文をそのまま出力しないこと。JSONは不要。

1. `# {book_title_ja} ブックガイド` で始める
2. `## 序論：{intro_subtitle}` の見出し
3. 200字程度の段落①：現代における本書の意義と問題提起
4. 200字程度の段落②：著者の中心的テーゼと本書が解き明かす核心
5. `## 本書の構成と読解フェーズ` の見出し
6. Markdown表（列：章番号、見出しタイトル、読解フェーズ、主なキーワード）
7. `## このガイドの使い方` の見出し
8. 100字程度のガイダンス段落

Markdownのみで回答。上記の数字リストや指示文を出力に含めないこと。
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

**執筆指示:**
以下の構成でこのセクションをMarkdownで執筆してください。JSONは不要です。指示文をそのまま出力しないこと。

1. `## 第{section_num}章 {heading_title}` で始める（この ## 見出し行は必ず出力すること）
2. 冒頭150-200字のイントロ段落（このセクションの問いと意義を述べる）
3. `### [著者の主張の核心を表すサブセクションタイトル]`（300-400字の詳細解説。著者の主張を忠実に再現しつつ、哲学的背景・類似概念・関連思想家も補足）
4. `### [別の角度からの掘り下げ（メカニズム、危険性、実践的含意など）]`（300-400字の詳細解説。具体例を2-3個含める。現代的事例も歓迎）
5. `### [他セクションとの接続または本セクションの小括]`（100-150字の締めくくりと次章への橋渡し）

**品質要件:**
- 日本語の専門概念には英訳を（カッコ）内に付ける
- 学術的だが一般読者にも読みやすい文体
- Markdownのみで回答（JSONは不要）
- 上記の指示文・説明文を出力に含めないこと
"""

CHECKLIST_PROMPT = """\
あなたは哲学書のブックガイドの実践ガイドを執筆する専門家です。

## 書籍
タイトル: {book_title_ja}（著者: {author_ja}）
全体テーマ: {work_description}

## 本書の章構成（実際の章タイトルを使うこと）
{headings_list}

## 本書の未解決の問い（アポリア）
{aporias_text}

## 主要概念
{concepts_text}

## 全体の論理展開
{logic_flow}

---

**執筆指示:**
本書『{book_title_ja}』の読者が本書の思想・洞察を実際に活かすための具体的なチェックリストをMarkdownで執筆してください。
上記「章構成」に記載された実際の章タイトルを使って、各フェーズが対応する章を明示すること。
指示文・説明文はそのまま出力しないこと。JSONは不要。

出力形式:

## 実践ガイド：『{book_title_ja}』を読んで実践するためのチェックリスト

（本書の要点と実践の意義を100字程度で述べる段落）

### フェーズ1：[第1-2章に対応したフェーズ名]

- [ ] （具体的なアクション）
- [ ] （具体的なアクション）
- [ ] （具体的なアクション）

### フェーズ2：[第3-5章に対応したフェーズ名]

- [ ] ...

### フェーズ3：[第6-8章に対応したフェーズ名]

- [ ] ...

（本書の意義を一文で述べる締めくくり）

**品質要件:** 本書固有の概念・論理展開に基づいて記述すること。読者が明日から実践できる具体的な行動レベルで記述すること。Markdownのみで回答。
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
    # Derive a subtitle from work_description (Japanese from book config) or logic_flow
    if work_description and len(work_description) > 10:
        # Take first sentence or up to 40 chars
        first_sentence = work_description.split("。")[0] if "。" in work_description else work_description
        intro_subtitle = first_sentence[:40].rstrip("。、") + "――その問いと意義"
    elif logic_flow and len(logic_flow) > 10:
        intro_subtitle = logic_flow[:40].rstrip("。、") + "――その核心"
    else:
        intro_subtitle = f"{book_title_ja}を読む――その問いと意義"

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
    _t0 = time.time()
    intro_md = llm.invoke(intro_prompt).content.strip()
    event_log.llm("web_researcher/guide_writer", "write_intro", model, time.time() - _t0)

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
        _t0 = time.time()
        section_md = llm.invoke(section_prompt).content.strip()
        event_log.llm("web_researcher/guide_writer", f"write_section[{i+1}/{total}]", model, time.time() - _t0)
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
        work_description=work_description[:300],
        headings_list=headings_list,
        aporias_text=aporias_text,
        concepts_text=concepts_text,
        logic_flow=logic_flow[:800],
    )
    _t0 = time.time()
    checklist_md = llm.invoke(checklist_prompt).content.strip()
    event_log.llm("web_researcher/guide_writer", "write_checklist", model, time.time() - _t0)

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
