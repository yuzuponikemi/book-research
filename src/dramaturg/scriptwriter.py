"""Persona-aware Japanese dialogue generation via Ollama."""

import json

from langchain_ollama import ChatOllama

from src.logger import create_step, extract_json
from src.models import Script


SCRIPT_PROMPT = """\
あなたは一流のポッドキャスト台本作家です。10分程度の哲学ポッドキャストの台本を書いてください。
二人の登場人物による、深く、知的で、聴き応えのある日本語の対話を生成してください。

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
タイトル: {title}
テーマ: {theme}
認知的ブリッジ（現代との接点）: {cognitive_bridge}

## 扱う概念
{concepts_text}

## 扱うアポリア（未解決の問い）
{aporias_text}

## 台本の構成（10分のエピソード）

以下の3幕構成で対話を展開してください：

### 第1幕：導入と問題提起（約3分 / 15-20発言）
- opening_bridgeで前回を振り返り、今回のテーマへ自然に導入する
- 現代の具体的なシナリオ（AI、SNS、スタートアップ等）から哲学的問いを引き出す
- リスナーが「自分にも関係ある」と感じるような入口を作る

### 第2幕：哲学的掘り下げ（約5分 / 20-30発言）
- 原著の概念を一つずつ丁寧に掘り下げる
- 原著の引用を自然に織り込む（最低3箇所）
- 二人が対立したり、意見が食い違う場面を含める
- 具体例、思考実験、現代の事例を交えて抽象的な概念を生き生きとさせる
- アポリア（未解決の問い）に正面から取り組み、簡単には答えを出さない

### 第3幕：統合と余韻（約2分 / 10-15発言）
- 議論を一段高い視点からまとめる（ただし完全な結論は出さない）
- リスナーが自分で考え続けたくなるような問いを残す
- closing_hookで次回への期待を高める

## 品質基準
- 対話は合計 **50-65発言** 程度（10分の朗読に相当）
- 各発言は1-4文。特に重要な場面では長めの発言を許可する
- 自然な日本語で書くこと（翻訳調にしないこと）
- 登場人物の個性が一貫して表現されていること
- 哲学的な深さと、日常的な親しみやすさのバランスを取ること
- 笑い、驚き、沈黙の間など、感情の起伏を含めること

以下のJSON形式で回答してください:
{{
  "episode_number": {episode_number},
  "title": "{title}",
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
        quotes = "\n".join(f'    「{q}」' for q in c.get("original_quotes", [])[:3])
        entry = f"- **{c['name']}**（{c['id']}）: {c['description']}"
        if quotes:
            entry += f"\n  原著の引用（対話で活用すること）:\n{quotes}"
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
        entry = f"- **{a['question']}**\n  背景: {a['context']}\n  関連概念: {', '.join(a.get('related_concepts', []))}"
        if a.get("id") in aporia_ids:
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

    pa = persona_config["persona_a"]
    pb = persona_config["persona_b"]

    scripts = []
    episodes = syllabus.get("episodes", [])
    for ep_idx, episode in enumerate(episodes):
        ep_num = episode.get("episode_number", ep_idx + 1)
        ep_title = episode.get("title", "?")
        print(f"      [{ep_idx+1}/{len(episodes)}] Writing Ep{ep_num}: {ep_title}...", end="", flush=True)

        concepts_text = _format_concepts(concept_graph, episode.get("concept_ids", []))
        aporias_text = _format_aporias(concept_graph, episode.get("aporia_ids", []))

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
            title=episode.get("title", ""),
            theme=episode.get("theme", ""),
            cognitive_bridge=episode.get("cognitive_bridge", ""),
            concepts_text=concepts_text,
            aporias_text=aporias_text,
            episode_number=episode.get("episode_number", 1),
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
