#!/usr/bin/env python3
"""
gemma4 benchmark — Ollama vs MLX (MTP Speculative Decoding)
=============================================================
Measures: TTFT, total time, tokens/s, output quality across
task types relevant to the cogito / factfull pipelines.

Requests go through OllamaProx (port 11435) so all runs are logged to the
dashboard. OllamaProx routes based on model name (routing.json):

  Ollama (direct autoregressive):
    gemma4:e4b          E4B MoE ~9.6GB Q4
    gemma4:26b          26B-A4B MoE ~17GB Q4

  MLX (MTP speculative decoding — start mlx_lm.server first):
    gemma4:e4b-mlx      E4B BF16 + E4B-assistant drafter
    gemma4:26b-mlx      26B-A4B BF16 + 26B-A4B-assistant drafter

Start MLX server before running MLX comparisons (see routing.json _server_cmd).

Usage:
  uv run python scripts/bench_gemma4.py                              # e4b: Ollama vs MLX
  uv run python scripts/bench_gemma4.py --models gemma4:26b gemma4:26b-mlx  # 26B comparison
  uv run python scripts/bench_gemma4.py --tasks json_short japanese --runs 3
  uv run python scripts/bench_gemma4.py --proxy http://localhost:11434  # bypass proxy
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Iterator

import httpx

# Route through OllamaProx so all runs appear in the dashboard.
# OllamaProx dispatches to Ollama or MLX based on routing.json.
OLLAMA_URL = "http://localhost:11435"


# ── Task definitions ──────────────────────────────────────────────────────────

TASKS = {
    "json_short": {
        "label": "JSON (短文・構造化)",
        "prompt": (
            "以下の本を分析し、JSON形式で3つのキーコンセプトを抽出してください。\n\n"
            "本: ガイ・ドゥボール『スペクタクルの社会』\n\n"
            'JSON形式: {"concepts": [{"id": "...", "name": "...", "description": "..."}]}'
        ),
        "num_ctx": 4096,
        "num_predict": 512,
        "format": "json",
    },
    "json_long": {
        "label": "JSON (長文・ダイアログ生成)",
        "prompt": (
            "あなたは哲学ポッドキャストの台本作家です。\n"
            "以下の概念について、教授と学生の対話を15往復（30発言）書いてください。\n\n"
            "テーマ: スペクタクルとは何か — ドゥボールの商品フェティシズム批判\n\n"
            "JSON形式で回答:\n"
            '{"dialogue": [{"speaker": "教授 or 学生", "line": "発言内容（50文字以上）"}]}'
        ),
        "num_ctx": 8192,
        "num_predict": 4096,
        "format": "json",
    },
    "japanese": {
        "label": "日本語長文生成",
        "prompt": (
            "ガイ・ドゥボール『スペクタクルの社会』を読んだことのない人向けに、"
            "この本の核心的な主張を1000字程度で解説してください。"
            "具体例（SNS、広告、メディア）を交えて、現代との関連性も示してください。"
        ),
        "num_ctx": 8192,
        "num_predict": 2048,
        "format": None,
    },
    "coding": {
        "label": "コーディング (Python)",
        "prompt": (
            "Write a Python function `extract_concepts(text: str) -> list[dict]` that:\n"
            "1. Takes a philosophical text as input\n"
            "2. Uses regex to find key terms (capitalized words or quoted terms)\n"
            "3. Returns a list of dicts with keys: 'term', 'count', 'context' (first sentence containing the term)\n"
            "Include type hints, docstring, and a usage example.\n"
            "Make it production-quality with error handling."
        ),
        "num_ctx": 8192,
        "num_predict": 2048,
        "format": None,
    },
    "reasoning": {
        "label": "論理推論・分析",
        "prompt": (
            "以下の主張を批判的に分析してください:\n\n"
            "「SNSは現代のスペクタクルであり、ユーザーは能動的な主体ではなく、"
            "受動的な観客に成り下がっている。したがって、SNSを使うこと自体が"
            "ドゥボールが批判した疎外の再生産である。」\n\n"
            "この主張の強み、弱み、論理的な飛躍、および反論をそれぞれ挙げ、"
            "最終的にあなたの見解を述べてください。"
        ),
        "num_ctx": 8192,
        "num_predict": 2048,
        "format": None,
    },
    "factcheck": {
        "label": "ファクトチェック (短文・高速)",
        "prompt": (
            "以下のクレームが事実かどうか判定し、JSONで回答してください:\n\n"
            "クレーム: 「ガイ・ドゥボールは1994年に自殺した」\n\n"
            '{"verdict": "true/false/uncertain", "confidence": 0-100, "reasoning": "..."}'
        ),
        "num_ctx": 2048,
        "num_predict": 256,
        "format": "json",
    },
}


# ── Ollama streaming call ─────────────────────────────────────────────────────

@dataclass
class RunResult:
    model: str
    task_id: str
    task_label: str
    ttft_ms: float        # time to first token
    total_ms: float       # total generation time
    prompt_tokens: int
    gen_tokens: int
    tokens_per_sec: float
    output: str
    error: str = ""


def _stream_generate(model: str, prompt: str, num_ctx: int, num_predict: int,
                     fmt: str | None) -> Iterator[tuple[str, dict]]:
    """Yield (token_text, final_stats_or_empty) tuples from Ollama streaming API."""
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": 0.1,
        },
    }
    if fmt:
        payload["format"] = fmt

    with httpx.stream("POST", f"{OLLAMA_URL}/api/generate",
                      json=payload, timeout=600) as resp:  # OLLAMA_URL patched by --proxy
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            token = data.get("response", "")
            yield token, data if data.get("done") else {}


def run_single(model: str, task_id: str, task: dict) -> RunResult:
    prompt = task["prompt"]
    num_ctx = task["num_ctx"]
    num_predict = task["num_predict"]
    fmt = task.get("format")

    tokens: list[str] = []
    ttft_ms = 0.0
    t_start = time.perf_counter()
    final_stats: dict = {}
    error = ""

    try:
        first = True
        for token, stats in _stream_generate(model, prompt, num_ctx, num_predict, fmt):
            if first and token:
                ttft_ms = (time.perf_counter() - t_start) * 1000
                first = False
            tokens.append(token)
            if stats:
                final_stats = stats
    except Exception as e:
        error = str(e)

    total_ms = (time.perf_counter() - t_start) * 1000
    output = "".join(tokens)
    gen_tokens = final_stats.get("eval_count", len(output) // 3)
    prompt_tokens = final_stats.get("prompt_eval_count", 0)
    tps = (gen_tokens / (total_ms / 1000)) if total_ms > 0 else 0

    return RunResult(
        model=model,
        task_id=task_id,
        task_label=task["label"],
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        prompt_tokens=prompt_tokens,
        gen_tokens=gen_tokens,
        tokens_per_sec=tps,
        output=output,
        error=error,
    )


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_separator(char="─", width=90):
    print(char * width)


def summarize(results: list[RunResult], models: list[str], task_ids: list[str]):
    # Group by (task, model) → list of RunResult
    from collections import defaultdict
    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for r in results:
        grouped[(r.task_id, r.model)].append(r)

    print("\n")
    print_separator("═")
    print("  BENCHMARK RESULTS")
    print_separator("═")

    for task_id in task_ids:
        task_label = TASKS[task_id]["label"]
        print(f"\n📋 {task_label}  [{task_id}]")
        print_separator()

        header = f"  {'モデル':<35} {'TTFT':>8} {'合計':>8} {'tok/s':>7} {'gen_tok':>8}  エラー"
        print(header)
        print_separator()

        for model in models:
            runs = grouped.get((task_id, model), [])
            if not runs:
                print(f"  {model:<35}  (no data)")
                continue
            good = [r for r in runs if not r.error]
            if not good:
                print(f"  {model:<35}  ERROR: {runs[0].error[:50]}")
                continue

            ttft  = statistics.mean(r.ttft_ms for r in good)
            total = statistics.mean(r.total_ms for r in good)
            tps   = statistics.mean(r.tokens_per_sec for r in good)
            gtok  = statistics.mean(r.gen_tokens for r in good)
            n     = len(good)
            suffix = f"(n={n})" if n > 1 else ""
            print(f"  {model:<35} {ttft:>7.0f}ms {total/1000:>7.1f}s {tps:>7.1f} {gtok:>8.0f}  {suffix}")

        print_separator()

    # Speed comparison summary
    print("\n🏁 速度比較サマリー (tokens/s 平均)")
    print_separator()
    model_avg: dict[str, list[float]] = {m: [] for m in models}
    for task_id in task_ids:
        for model in models:
            runs = grouped.get((task_id, model), [])
            good = [r for r in runs if not r.error]
            if good:
                model_avg[model].append(statistics.mean(r.tokens_per_sec for r in good))

    baseline = None
    for model in models:
        vals = model_avg[model]
        avg = statistics.mean(vals) if vals else 0
        if baseline is None:
            baseline = avg
            delta = ""
        else:
            pct = ((avg - baseline) / baseline * 100) if baseline else 0
            delta = f"  ({pct:+.1f}% vs {models[0]})"
        print(f"  {model:<40} {avg:>7.1f} tok/s{delta}")
    print_separator()


def show_outputs(results: list[RunResult], models: list[str], task_ids: list[str]):
    print("\n\n📄 出力サンプル（最終ラン）")
    from collections import defaultdict
    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for r in results:
        grouped[(r.task_id, r.model)].append(r)

    for task_id in task_ids:
        print(f"\n{'═'*90}")
        print(f"  TASK: {TASKS[task_id]['label']}")
        print(f"{'═'*90}")
        for model in models:
            runs = grouped.get((task_id, model), [])
            if not runs:
                continue
            last = runs[-1]
            print(f"\n  ── {model} ──")
            out = last.output if not last.error else f"ERROR: {last.error}"
            # Show first 600 chars
            preview = out[:600] + ("…" if len(out) > 600 else "")
            for line in preview.splitlines():
                print(f"    {line}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="gemma4 モデル比較ベンチマーク")
    parser.add_argument("--models", nargs="+",
                        default=["qwen3.5:latest", "qwen3.6-27b:mtp"])
    parser.add_argument("--tasks", nargs="+", default=list(TASKS.keys()),
                        choices=list(TASKS.keys()))
    parser.add_argument("--runs", type=int, default=2,
                        help="各タスク・モデルの試行回数")
    parser.add_argument("--no-output", action="store_true",
                        help="出力サンプル表示をスキップ")
    parser.add_argument("--proxy", default=None,
                        help="Ollama/OllamaProx URL (デフォルト: http://localhost:11435)")
    args = parser.parse_args()

    if args.proxy:
        import sys
        # Patch the module-level constant at runtime
        import __main__
        __main__.OLLAMA_URL = args.proxy
        # Also patch the function's closure reference
        global OLLAMA_URL
        OLLAMA_URL = args.proxy

    print(f"{'═'*90}")
    print(f"  LLM Benchmark  —  {len(args.models)} models × {len(args.tasks)} tasks × {args.runs} runs")
    print(f"{'═'*90}")
    print(f"  Models : {', '.join(args.models)}")
    print(f"  Tasks  : {', '.join(args.tasks)}")
    print(f"  Proxy  : {OLLAMA_URL}")
    print()

    # Show server_cmd hint for MLX/MTP models
    mlx_models = [m for m in args.models if m.endswith('-mlx') or ':mtp' in m or ':no-mtp' in m]
    if mlx_models:
        try:
            import urllib.request
            routing = json.loads(urllib.request.urlopen(
                f"{OLLAMA_URL}/api/routing", timeout=2).read())
            for m in mlx_models:
                cmd = routing.get("routes", {}).get(m, {}).get("_server_cmd", "")
                if cmd:
                    print(f"  [MLX] {m} サーバー起動コマンド:")
                    print(f"        {cmd}")
            print()
        except Exception:
            pass

    all_results: list[RunResult] = []

    for run_i in range(1, args.runs + 1):
        print(f"\n{'─'*90}")
        print(f"  Run {run_i}/{args.runs}")
        print(f"{'─'*90}")

        for task_id in args.tasks:
            task = TASKS[task_id]
            for model in args.models:
                print(f"  [{task_id}] {model} ... ", end="", flush=True)
                result = run_single(model, task_id, task)
                all_results.append(result)
                if result.error:
                    print(f"ERROR: {result.error[:60]}")
                else:
                    print(f"ttft={result.ttft_ms:.0f}ms  total={result.total_ms/1000:.1f}s  "
                          f"{result.tokens_per_sec:.1f} tok/s  gen={result.gen_tokens}tok")

    summarize(all_results, args.models, args.tasks)
    if not args.no_output:
        show_outputs(all_results, args.models, args.tasks)

    # Save raw results
    out_path = "scripts/bench_results.json"
    raw = [
        {
            "model": r.model, "task": r.task_id, "label": r.task_label,
            "ttft_ms": round(r.ttft_ms, 1), "total_ms": round(r.total_ms, 1),
            "prompt_tokens": r.prompt_tokens, "gen_tokens": r.gen_tokens,
            "tokens_per_sec": round(r.tokens_per_sec, 2),
            "error": r.error, "output_len": len(r.output),
        }
        for r in all_results
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print(f"\n  Raw results → {out_path}")


if __name__ == "__main__":
    main()
