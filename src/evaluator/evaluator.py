"""Script quality evaluator — scores dialogue and triggers regeneration if below threshold."""

import json
from pathlib import Path
from langchain_ollama import ChatOllama
from src.logger import create_step

EVAL_PROMPT = """You are a podcast script quality evaluator. Score this Japanese dialogue script.

Script:
{script}

Episode plan:
{syllabus_context}

Score each dimension 1-5:
- naturalness: 会話の自然さ（ぎこちなくないか）
- depth: 内容の深さ（概念・アポリアが議論されているか）
- engagement: 聴取者を引き込む力
- length_ok: 適切な長さ（10以上の発話があるか）→ 5=十分, 1=短すぎる
- japanese_quality: 日本語の品質

Return JSON only:
{{
  "naturalness": <1-5>,
  "depth": <1-5>,
  "engagement": <1-5>,
  "length_ok": <1-5>,
  "japanese_quality": <1-5>,
  "overall": <1-5>,
  "feedback": "<one sentence of constructive feedback in Japanese>"
}}"""


def evaluate_scripts(state: dict) -> dict:
    """Evaluate generated scripts and flag for regeneration if quality is low."""
    scripts = state.get("scripts", [])
    if not scripts:
        return {"eval_scores": [], "needs_regen": False}

    model = state.get("reader_model", "llama3.2:latest")
    llm = ChatOllama(model=model, temperature=0.1, format="json")

    scores = []
    needs_regen = False
    threshold = state.get("eval_threshold", 3.0)

    for i, script in enumerate(scripts):
        dialogue = script.get("dialogue", "")
        if not dialogue:
            scores.append({"overall": 1, "feedback": "スクリプトが空です", "regenerate": True})
            needs_regen = True
            continue

        syllabus_context = ""
        if state.get("syllabus"):
            episodes = state["syllabus"].get("episodes", [])
            if i < len(episodes):
                ep = episodes[i]
                syllabus_context = f"Title: {ep.get('title', '')}\nCore tension: {ep.get('core_tension', '')}"

        try:
            prompt = EVAL_PROMPT.format(script=dialogue[:3000], syllabus_context=syllabus_context)
            response = llm.invoke(prompt).content
            score_data = json.loads(response)
            overall = float(score_data.get("overall", 3))
            regenerate = overall < threshold or score_data.get("length_ok", 5) < 3
            score_data["regenerate"] = regenerate
            scores.append(score_data)
            if regenerate:
                needs_regen = True
        except Exception as e:
            scores.append({"overall": 2, "feedback": f"評価エラー: {e}", "regenerate": False})

    # Save scores to run directory
    run_dir = state.get("run_dir")
    if run_dir:
        scores_path = Path(run_dir) / "eval_scores.json"
        scores_path.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"eval_scores": scores, "needs_regen": needs_regen, "regen_count": state.get("regen_count", 0) + 1}
