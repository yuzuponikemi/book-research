"""Persona-aware Japanese dialogue generation via Ollama."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.models import Script


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
- 原著の核心的なフレーズ（「我思う、ゆえに我あり」等）は会話の中で自然に言及してよいが、長い原文の引用は避ける
- 二人が対立したり、意見が食い違う場面を含める
- 具体例、思考実験、現代の事例を交えて抽象的な概念を生き生きとさせる
- アポリア（未解決の問い）に正面から取り組み、簡単には答えを出さない
{act2_extra}

### 第3幕：統合と余韻（約2分 / 10-15発言）
- 議論を一段高い視点からまとめる（ただし完全な結論は出さない）
- 今回のエピソードで扱った『{book_title_ja}』の論点を振り返る
- リスナーが自分で考え続けたくなるような問いを残す
- closing_hookで次回への期待を高める
{act3_extra}

## 品質基準
- 対話は合計 **50-65発言** 程度（10分の朗読に相当）
- 各発言は1-4文。特に重要な場面では長めの発言を許可する
- **全ての対話は必ず日本語で書くこと**。登場人物が哲学者であっても、台詞は全て日本語にすること。英語の台詞は絶対に含めないこと
- 自然な日本語で書くこと（翻訳調にしないこと）
- 登場人物の個性が一貫して表現されていること
- 哲学的な深さと、日常的な親しみやすさのバランスを取ること
- この対話が『{book_title_ja}』の解説であることが、聴き手に明確に伝わること
- 笑い、驚き、沈黙の間など、感情の起伏を含めること

【重要】全ての出力は日本語で書いてください。title, opening_bridge, dialogue, closing_hook の全てが日本語であること。英語を混ぜないでください。

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


def _format_concepts(concept_graph: dict, concept_ids: list[str]) -> str:
    """Format selected concepts for the prompt, with primary/secondary distinction."""
    concepts = concept_graph.get("concepts", [])
    primary_lines = []
    secondary_lines = []
    for c in concepts:
        if isinstance(c, str):
            entry = f"- {c[:200]}"
            secondary_lines.append(entry)
            continue
        quotes = "\n".join(f'    「{q}」' for q in c.get("original_quotes", [])[:3])
        entry = f"- **{c.get('name', '?')}**（{c.get('id', '?')}）: {c.get('description', '')}"
        if quotes:
            entry += f"\n  原著の該当箇所（参考情報。対話では自分の言葉で言い換えること）:\n{quotes}"
        if c.get("id") in concept_ids:
            primary_lines.append(entry)
        else:
            secondary_lines.append(entry)

    parts = []
    if primary_lines:
        parts.append("### 主要概念（このエピソードの中心）\n" + "\n\n".join(primary_lines))
    if secondary_lines:
        parts.append("### 補助概念（背景知識として参照可能）\n" + "\n\n".join(secondary_lines))
    return "\n\n".join(parts) if parts else "（概念情報なし）"


def _format_aporias(concept_graph: dict, aporia_ids: list[str]) -> str:
    """Format selected aporias for the prompt."""
    aporias = concept_graph.get("aporias", [])
    primary_lines = []
    secondary_lines = []
    for a in aporias:
        if isinstance(a, str):
            entry = f"- {a[:200]}"
        else:
            q = a.get('question', a.get('name', '?'))
            ctx = a.get('context', '')
            related = a.get('related_concepts', [])
            entry = f"- **{q}**\n  背景: {ctx}\n  関連概念: {', '.join(related)}"
        if isinstance(a, dict) and a.get("id") in aporia_ids:
            primary_lines.append(entry)
        else:
            secondary_lines.append(entry)

    parts = []
    if primary_lines:
        parts.append("### 主要アポリア（このエピソードで正面から扱うこと）\n" + "\n\n".join(primary_lines))
    if secondary_lines:
        parts.append("### 補助アポリア（言及可能）\n" + "\n\n".join(secondary_lines))
    return "\n\n".join(parts) if parts else "（アポリア情報なし）"


def write_scripts(state: dict) -> dict:
    """LangGraph node: generate dialogue scripts for each episode."""
    syllabus = state["syllabus"]
    concept_graph = state["concept_graph"]
    persona_config = state["persona_config"]
    steps = list(state.get("thinking_log", []))

    model = state.get("dramaturg_model", "qwen3-next")
    llm = ChatOllama(model=model, temperature=0.7, num_ctx=32768)

    book_config = state.get("book_config", {})
    book = book_config.get("book", {})
    enrichment = state.get("enrichment", {})

    book_title = book.get("title", state.get("book_title", ""))
    book_title_ja = book.get("title_ja", book_title)
    author_ja = book.get("author_ja", book.get("author", ""))

    pa = persona_config["persona_a"]
    pb = persona_config["persona_b"]

    scripts = []
    episodes = syllabus.get("episodes", [])
    total_episodes = len(episodes)

    for ep_idx, episode in enumerate(episodes):
        ep_num = episode.get("episode_number", ep_idx + 1)
        ep_title = episode.get("title", "?")
        print(f"      [{ep_idx+1}/{total_episodes}] Writing Ep{ep_num}: {ep_title}...", end="", flush=True)

        concepts_text = _format_concepts(concept_graph, episode.get("concept_ids", []))
        aporias_text = _format_aporias(concept_graph, episode.get("aporia_ids", []))

        # Build episode-specific context
        is_first = (ep_idx == 0)
        is_last = (ep_idx == total_episodes - 1)

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
            prev_ep = episodes[ep_idx - 1]
            episode_context = (
                f"これはシリーズの最終回です。\n"
                f"前回（第{ep_idx}回）のテーマ: {prev_ep.get('theme', '')}"
            )
            act1_instruction = (
                "- opening_bridgeで前回の議論を振り返り、今回のテーマへ自然に導入する\n"
                "- シリーズ全体のまとめも意識する"
            )
        else:
            prev_ep = episodes[ep_idx - 1]
            next_ep = episodes[ep_idx + 1] if ep_idx + 1 < total_episodes else None
            episode_context = f"前回（第{ep_idx}回）のテーマ: {prev_ep.get('theme', '')}"
            if next_ep:
                episode_context += f"\n次回（第{ep_idx + 2}回）のテーマ: {next_ep.get('theme', '')}"
            act1_instruction = (
                "- opening_bridgeで前回の議論を簡潔に振り返り、今回のテーマへ自然に導入する"
            )

        # Build enrichment block for script prompt
        enrichment_summary_ja = enrichment.get("enrichment_summary_ja", "")
        critique_perspectives_ja = enrichment.get("critique_perspectives_ja", "")

        enrichment_parts = []
        if enrichment_summary_ja:
            enrichment_parts.append(f"## 研究背景\n{enrichment_summary_ja}")
        if critique_perspectives_ja:
            enrichment_parts.append(f"## 批判的視点\n{critique_perspectives_ja}")
        enrichment_block = "\n\n".join(enrichment_parts)

        # Extra instructions for acts 2 and 3 when enrichment is available
        if enrichment_summary_ja:
            act2_extra = "- 少なくとも1つの歴史的批判に言及すること"
            act3_extra = "- 現代における再解釈や影響に言及すること"
        else:
            act2_extra = ""
            act3_extra = ""

        prompt = SCRIPT_PROMPT.format(
            persona_a_name=pa["name"],
            persona_a_role=pa["role"],
            persona_a_description=pa["description"],
            persona_a_tone=pa["tone"],
            persona_a_speaking_style=pa["speaking_style"],
            persona_b_name=pb["name"],
            persona_b_role=pb["role"],
            persona_b_description=pb["description"],
            persona_b_tone=pb["tone"],
            persona_b_speaking_style=pb["speaking_style"],
            theme=episode.get("theme", ""),
            cognitive_bridge=episode.get("cognitive_bridge", ""),
            concepts_text=concepts_text,
            aporias_text=aporias_text,
            episode_number=ep_num,
            total_episodes=total_episodes,
            episode_context=episode_context,
            act1_instruction=act1_instruction,
            book_title=book_title,
            book_title_ja=book_title_ja,
            author_ja=author_ja,
            enrichment_block=enrichment_block,
            act2_extra=act2_extra,
            act3_extra=act3_extra,
        )

        raw_response = llm.invoke(prompt).content

        parsed = None
        error = None
        try:
            parsed = extract_json(raw_response)
            Script(**parsed)
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            error = f"JSON parse error: {e}"
            parsed = parsed or {
                "episode_number": episode.get("episode_number", 1),
                "title": episode.get("title", ""),
                "opening_bridge": "",
                "dialogue": [],
                "closing_hook": "",
            }
        except Exception as e:
            error = f"Validation error: {e}"

        n_lines = len(parsed.get("dialogue", []))
        print(f" {n_lines} lines")

        scripts.append(parsed)

        steps.append(create_step(
            layer="dramaturg",
            node="scriptwriter",
            action=f"write_script:episode_{episode.get('episode_number', '?')}",
            input_summary=f"Episode {episode.get('episode_number')}: {episode.get('title', '')}",
            llm_prompt=prompt,
            llm_raw_response=raw_response,
            parsed_output=parsed,
            error=error,
            reasoning=f"Generated script with {len(parsed.get('dialogue', []))} dialogue lines "
                      f"using personas {pa['name']} and {pb['name']}",
        ))

    return {
        "scripts": scripts,
        "thinking_log": steps,
    }
