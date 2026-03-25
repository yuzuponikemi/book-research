"""Producer service — essay output mode.

Generates a structured analytical essay (解説エッセイ) alongside the podcast script.
The essay is saved as 06_essay.md in the run directory.
"""

from __future__ import annotations

import json
import os
import time

from langchain_ollama import ChatOllama

from cogito.utils import event_log
from cogito.utils.logger import create_step
from cogito.schemas.concept_graph import ConceptGraphV1


ESSAY_PROMPT = """\
あなたは哲学・思想の専門的な解説者です。
以下の概念グラフと書籍情報をもとに、深く、読み応えのある解説エッセイを日本語で書いてください。

## 書籍情報
タイトル: 『{book_title_ja}』（原題: {book_title}）
著者: {author_ja}（{author}）

## 概念グラフ
{concept_graph_json}

---

## エッセイの構成（以下の順に書くこと）

### 1. 序論：この本はなぜ今読まれるべきか（200〜300字）
- 著者がこの本を書いた時代的背景と動機
- この本が提起する中心的な問い
- 現代における意義（AI・テクノロジー・社会変化との接点）

### 2. 著者の中心的テーゼ（300〜400字）
- 著者が最終的に主張しようとしていること
- その主張を支える根本的な論理の骨格
- 他の思想家・哲学者との比較（必要に応じて）

### 3. 主要概念の解説（各概念につき200〜350字、全概念を扱うこと）
各概念について：
- その概念が著者の文脈でどういう意味を持つか
- なぜそれが必要なのか（他の概念との関係）
- 現代の具体的な事例に引きつけた説明
- 関連する他の概念への橋渡し

### 4. 概念間の関係と論理構造（300〜400字）
- 概念グラフのrelationsに基づいて、思想の論理的な流れを解説
- 「AがBを前提とし、CがAとBの矛盾から生まれる」といった構造を可視化
- 読者がこの本を「地図」として使えるような記述

### 5. 未解決の問い（アポリア）（各アポリアにつき150〜250字）
- 著者が格闘し、解決できなかった問い
- なぜ解決できないのか、何が障壁になっているのか
- この問いを引き受けて生きることの意味

### 6. 批判的考察（300〜400字）
- この思想の弱点・限界・見落としている視点
- 反論として成立しうる立場の紹介
- 著者自身も認識していた限界があれば言及

### 7. 現代への問いかけ（200〜300字）
- この本を読んだ後に、読者が持ち帰るべき問いを3つ提示
- 「この思想が正しいなら、私たちの〜はどう変わるか」という形で具体化

---

## 品質基準（厳守）
- 全体で2500〜4500字（充実した読み物として成立する長さ）
- 全文日本語（専門用語は初出時に説明すること）
- 概念グラフのoriginal_quotesから1〜2箇所を各概念解説に引用してよい（「」で囲む）
- 「わかりやすく」するためにシンプルにしすぎない。知的な読者を想定すること
- 章立ての見出しはそのまま使うこと（## 1. 序論：...）

Markdownで回答してください。JSONは不要です。
"""


def write_essay(
    concept_graph: ConceptGraphV1,
    book_config: dict,
    run_dir: str,
    model: str = "qwen3.5:latest",
) -> str:
    """Generate an analytical essay from the concept graph.

    Args:
        concept_graph: The unified ConceptGraphV1.
        book_config:   Book metadata dict (title, author, etc.).
        run_dir:       Directory to write 06_essay.md into.
        model:         Ollama model name for generation.

    Returns:
        Path to the generated essay file.
    """
    book = book_config.get("book", {})
    book_title = book.get("title", "Unknown Title")
    book_title_ja = book.get("title_ja", book_title)
    author = book.get("author", "Unknown Author")
    author_ja = book.get("author_ja", author)

    # Build a compact graph representation for the prompt
    graph_dict = {
        "concepts": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "original_quotes": c.original_quotes[:2],
            }
            for c in concept_graph.concepts
        ],
        "relations": [
            {
                "source": r.source,
                "target": r.target,
                "relation_type": r.relation_type,
                "evidence": r.evidence,
            }
            for r in concept_graph.relations
        ],
        "aporias": [
            {
                "id": a.id,
                "question": a.question,
                "context": a.context,
            }
            for a in concept_graph.aporias
        ],
        "core_frustration": concept_graph.core_frustration or "",
        "logic_flow": concept_graph.logic_flow or "",
    }

    num_ctx = 32768 if any(m in model for m in ("qwen3", "command-r")) else 16384
    llm = ChatOllama(model=model, temperature=0.6, num_ctx=num_ctx)

    prompt = ESSAY_PROMPT.format(
        book_title=book_title,
        book_title_ja=book_title_ja,
        author=author,
        author_ja=author_ja,
        concept_graph_json=json.dumps(graph_dict, ensure_ascii=False, indent=2),
    )

    # Disable thinking mode for reasoning models to prevent context exhaustion
    _is_thinking_model = any(m in model.lower() for m in ("qwen3", "deepseek-r1", "qwq"))
    invoke_prompt = f"/no_think\n\n{prompt}" if _is_thinking_model else prompt

    print("  [essay_writer] generating analytical essay...", end="", flush=True)
    _t0 = time.time()
    essay_text = llm.invoke(invoke_prompt).content
    elapsed = time.time() - _t0
    event_log.llm("producer/essay_writer", "write_essay", model, elapsed)
    print(f" done ({elapsed:.1f}s, {len(essay_text)} chars)")

    # Write to file
    essay_path = os.path.join(run_dir, "06_essay.md")
    header = f"# 解説エッセイ：『{book_title_ja}』（{author_ja}）\n\n"
    with open(essay_path, "w", encoding="utf-8") as f:
        f.write(header + essay_text)

    print(f"  [essay_writer] essay saved → {essay_path}")
    return essay_path
