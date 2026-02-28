"""Producer service — podcast scriptwriting stage (Dramaturg layer).

Ported and decoupled from src/dramaturg/scriptwriter.py.
CogitoState dependency removed; takes ConceptGraphV1 + SyllabusV1 directly.
"""

from __future__ import annotations

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.schemas.production import SyllabusV1, ScriptV1, PersonaConfig


# ── Script prompt (identical to src/dramaturg/scriptwriter.py) ────────────────

SCRIPT_PROMPT = """\
あなたは一流のポッドキャスト台本作家です。10分程度の哲学ポッドキャストの台本を書いてください。
二人の登場人物による、深く、知的で、聴き応えのある日本語の対話を生成してください。

## シリーズ情報
このポッドキャストは、{author_ja}の著書『{book_title_ja}』（原題：{book_title}）を \
全{total_episodes}回のシリーズで読み解く番組です。
今回は第{episode_number}回（全{total_episodes}回中）です。

{episode_context}

## 登場人物

### {persona_a_name}（{persona_a_role}）
{persona_a_description}
トーン: {persona_a_tone}
話し方: {persona_a_speaking_style}

### {persona_b_name}（{persona_b_role}）
{persona_b_description}
トーン: {persona_b_tone}
話し方: {persona_b_speaking_style}

## エピソード情報
テーマ: {theme}
認知的ブリッジ（現代との接点）: {cognitive_bridge}

## 扱う概念
{concepts_text}

## 扱うアポリア（未解決の問い）
{aporias_text}

{enrichment_block}

## 台本の構成（10分のエピソード）

以下の3幕構成で対話を展開してください：

### 第1幕：導入と問題提起（約3分 / 15-20発言）
{act1_instruction}
- 現代の具体的なシナリオ（AI、SNS、スタートアップ等）から哲学的問いを引き出す
- リスナーが「自分にも関係ある」と感じるような入口を作る
- 対話の中で『{book_title_ja}』のどの部分を扱うのかを自然に説明する

### 第2幕：哲学的掘り下げ（約5分 / 20-30発言）
- 原著の概念を一つずつ丁寧に掘り下げる
- 【重要】原文をそのまま引用・朗読しないこと。概念や主張は登場人物自身の言葉で噛み砕いて説明する
- 二人が対立したり、意見が食い違う場面を含める
- 具体例、思考実験、現代の事例を交えて抽象的な概念を生き生きとさせる
- アポリア（未解決の問い）に正面から取り組み、簡単には答えを出さない
{act2_extra}

### 第3幕：統合と余韻（約2分 / 10-15発言）
- 議論を一段高い視点からまとめる（ただし完全な結論は出さない）
- リスナーが自分で考え続けたくなるような問いを残す
- closing_hookで次回への期待を高める
{act3_extra}

## 品質基準
- 対話は合計 **50-65発言** 程度（10分の朗読に相当）
- **全ての対話は必ず日本語で書くこと**
- 自然な日本語で書くこと（翻訳調にしないこと）
- 登場人物の個性が一貫して表現されていること

以下のJSON形式で回答してください。titleは日本語で魅力的なものにすること:
{{
  "episode_number": {episode_number},
  "title": "（日本語のタイトルをここに）",
  "opening_bridge": "...",
  "dialogue": [
    {{"speaker": "{persona_a_name}", "line": "..."}},
    {{"speaker": "{persona_b_name}", "line": "..."}}
  ],
  "closing_hook": "..."
}}
"""


def _format_concepts(graph: ConceptGraphV1, concept_ids: list[str]) -> str:
    primary, secondary = [], []
    for c in graph.concepts:
        quotes = "\n".join(f'    「{q}」' for q in c.original_quotes[:3])
        entry = f"- **{c.name}**（{c.id}）: {c.description}"
        if quotes:
            entry += f"\n  原著の該当箇所（参考情報）:\n{quotes}"
        (primary if c.id in concept_ids else secondary).append(entry)
    parts = []
    if primary:
        parts.append("### 主要概念（このエピソードの中心）\n" + "\n\n".join(primary))
    if secondary:
        parts.append("### 補助概念（背景知識として参照可能）\n" + "\n\n".join(secondary))
    return "\n\n".join(parts) if parts else "（概念情報なし）"


def _format_aporias(graph: ConceptGraphV1, aporia_ids: list[str]) -> str:
    primary, secondary = [], []
    for a in graph.aporias:
        related = ", ".join(a.related_concepts)
        entry = f"- **{a.question}**\n  背景: {a.context}\n  関連概念: {related}"
        (primary if a.id in aporia_ids else secondary).append(entry)
    parts = []
    if primary:
        parts.append("### 主要アポリア（このエピソードで正面から扱うこと）\n" + "\n\n".join(primary))
    if secondary:
        parts.append("### 補助アポリア（言及可能）\n" + "\n\n".join(secondary))
    return "\n\n".join(parts) if parts else "（アポリア情報なし）"


def write_podcast_scripts(
    graph: ConceptGraphV1,
    syllabus: SyllabusV1,
    persona_config: PersonaConfig,
    book_title: str | None = None,
    book_title_ja: str | None = None,
    author_ja: str | None = None,
    enrichment: dict | None = None,
    dramaturg_model: str = "qwen3-next",
) -> tuple[list[ScriptV1], list[dict]]:
    """Generate dialogue scripts for every episode in the syllabus.

    Args:
        graph:            ConceptGraphV1 (for concept/aporia text).
        syllabus:         SyllabusV1 with episode definitions.
        persona_config:   Two-character persona definitions.
        book_title:       English book title (falls back to graph.subject).
        book_title_ja:    Japanese book title (falls back to book_title).
        author_ja:        Japanese author name.
        enrichment:       Optional enrichment dict for background context.
        dramaturg_model:  Ollama model for script generation.

    Returns:
        (list[ScriptV1], thinking_log_entries)
    """
    llm = ChatOllama(model=dramaturg_model, temperature=0.7, num_ctx=32768)

    book_title = book_title or graph.subject
    book_title_ja = book_title_ja or book_title
    author_ja = author_ja or ""
    enrichment = enrichment or {}

    pa = persona_config.persona_a
    pb = persona_config.persona_b

    scripts: list[ScriptV1] = []
    log: list[dict] = []
    episodes = syllabus.episodes
    total_episodes = len(episodes)

    for ep_idx, episode in enumerate(episodes):
        ep_num = episode.episode_number
        print(f"      [{ep_idx+1}/{total_episodes}] Writing Ep{ep_num}: {episode.title}...",
              end="", flush=True)

        concepts_text = _format_concepts(graph, episode.concept_ids)
        aporias_text  = _format_aporias(graph, episode.aporia_ids)

        is_first = (ep_idx == 0)
        is_last  = (ep_idx == total_episodes - 1)

        if is_first:
            episode_context = (
                "これはシリーズの第1回です。リスナーはまだこの番組を聴いたことがありません。\n"
                f"『{book_title_ja}』とは何か、なぜ今この本を読むのかを紹介してください。"
            )
            act1_instruction = (
                "- 【重要】第1回なので「前回」への言及は絶対にしないこと\n"
                f"- opening_bridgeでは、番組の紹介と『{book_title_ja}』という書籍の導入を行う\n"
                f"- {author_ja}がどのような人物で、なぜ『{book_title_ja}』が重要なのかを自然に紹介する"
            )
        elif is_last:
            prev = episodes[ep_idx - 1]
            episode_context = f"これはシリーズの最終回です。\n前回（第{ep_idx}回）のテーマ: {prev.theme}"
            act1_instruction = (
                "- opening_bridgeで前回の議論を振り返り、今回のテーマへ自然に導入する\n"
                "- シリーズ全体のまとめも意識する"
            )
        else:
            prev = episodes[ep_idx - 1]
            next_ep = episodes[ep_idx + 1] if ep_idx + 1 < total_episodes else None
            episode_context = f"前回（第{ep_idx}回）のテーマ: {prev.theme}"
            if next_ep:
                episode_context += f"\n次回（第{ep_idx + 2}回）のテーマ: {next_ep.theme}"
            act1_instruction = "- opening_bridgeで前回の議論を簡潔に振り返り、今回のテーマへ自然に導入する"

        enrichment_parts = []
        if enrichment.get("enrichment_summary_ja"):
            enrichment_parts.append(f"## 研究背景\n{enrichment['enrichment_summary_ja']}")
        if enrichment.get("critique_perspectives_ja"):
            enrichment_parts.append(f"## 批判的視点\n{enrichment['critique_perspectives_ja']}")
        enrichment_block = "\n\n".join(enrichment_parts)

        act2_extra = "- 少なくとも1つの歴史的批判に言及すること" if enrichment.get("enrichment_summary_ja") else ""
        act3_extra = "- 現代における再解釈や影響に言及すること" if enrichment.get("enrichment_summary_ja") else ""

        prompt = SCRIPT_PROMPT.format(
            persona_a_name=pa.name, persona_a_role=pa.role,
            persona_a_description=pa.description, persona_a_tone=pa.tone,
            persona_a_speaking_style=pa.speaking_style,
            persona_b_name=pb.name, persona_b_role=pb.role,
            persona_b_description=pb.description, persona_b_tone=pb.tone,
            persona_b_speaking_style=pb.speaking_style,
            theme=episode.theme, cognitive_bridge=episode.cognitive_bridge,
            concepts_text=concepts_text, aporias_text=aporias_text,
            episode_number=ep_num, total_episodes=total_episodes,
            episode_context=episode_context, act1_instruction=act1_instruction,
            book_title=book_title, book_title_ja=book_title_ja, author_ja=author_ja,
            enrichment_block=enrichment_block,
            act2_extra=act2_extra, act3_extra=act3_extra,
        )

        raw_response = llm.invoke(prompt).content
        parsed: dict | None = None
        error: str | None = None
        try:
            parsed = extract_json(raw_response)
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            error = f"JSON parse error: {e}"
            parsed = {
                "episode_number": ep_num, "title": episode.title,
                "opening_bridge": "", "dialogue": [], "closing_hook": "",
            }

        n_lines = len(parsed.get("dialogue", []))
        print(f" {n_lines} lines")

        script = ScriptV1.from_legacy_dict(parsed, subject=graph.subject)
        scripts.append(script)

        log.append(create_step(
            layer="producer", node="scriptwriter",
            action=f"write_script:episode_{ep_num}",
            input_summary=f"Episode {ep_num}: {episode.title}",
            llm_prompt=prompt, llm_raw_response=raw_response,
            parsed_output=parsed, error=error,
            reasoning=f"Generated {n_lines} dialogue lines with {pa.name} and {pb.name}",
        ))

    return scripts, log
