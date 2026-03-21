#!/usr/bin/env python3
"""
run_pipeline.py — Cogito pipeline runner with Telegram IPC progress reporting.

Telegramから書名を受け取り、パイプラインを実行して進捗・結果をTelegramへ送信する。

Usage:
    python3 run_pipeline.py --book "デカルト" --chat-jid tg:-5218254973
    python3 run_pipeline.py --book attention --chat-jid tg:-5218254973 --full
    python3 run_pipeline.py --book plurality --chat-jid tg:-5218254973 --group-folder telegram_main

Flags:
    --book          書名またはエイリアス（日本語・英語両対応）
    --chat-jid      Telegram チャットJID（必須）
    --group-folder  nanoclaw グループフォルダ名 (default: telegram_main)
    --fast          --skip-audio --skip-research（デフォルト、~2-5分）
    --full          リサーチあり（--skip-audio のみ、~5-15分）
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import yaml as _yaml  # PyYAML（オプション）
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

BOOK_RESEARCH_DIR = Path(__file__).parent
IPC_MESSAGES_DIR = Path("/workspace/ipc/messages")

# ---------------------------------------------------------------------------
# 書名エイリアステーブル
# ---------------------------------------------------------------------------

BOOK_ALIASES: dict[str, str] = {
    # Descartes: Discourse on the Method
    "descartes_discourse": "descartes_discourse",
    "descartes":           "descartes_discourse",
    "discourse":           "descartes_discourse",
    "cogito":              "descartes_discourse",
    "デカルト":            "descartes_discourse",
    "方法序説":            "descartes_discourse",
    "デカルト方法序説":    "descartes_discourse",
    "方法について":        "descartes_discourse",
    # Attention is All You Need
    "attention":           "attention",
    "transformer":         "attention",
    "vaswani":             "attention",
    "アテンション":        "attention",
    "トランスフォーマー":  "attention",
    # Plurality
    "plurality":           "plurality",
    "audrey tang":         "plurality",
    "tang":                "plurality",
    "weyl":                "plurality",
    "プルラリティ":        "plurality",
    "多元性":              "plurality",
    "オードリー・タン":    "plurality",
}

BOOK_LABELS: dict[str, str] = {
    "descartes_discourse": "Discourse on the Method (Descartes, 1637)",
    "attention":           "Attention Is All You Need (Vaswani et al., 2017)",
    "plurality":           "Plurality (Audrey Tang & Glen Weyl, 2024)",
}

AVAILABLE_BOOKS_MSG = (
    "📚 Cogito: 利用可能な書籍\n\n"
    "• デカルト / descartes / 方法序説 → Discourse on the Method\n"
    "• アテンション / attention / transformer → Attention Is All You Need\n"
    "• プルラリティ / plurality / audrey tang → Plurality\n\n"
    "使い方: /cogito デカルト"
)

# ---------------------------------------------------------------------------
# IPC ヘルパー
# ---------------------------------------------------------------------------

def send_ipc(text: str, chat_jid: str, group_folder: str) -> None:
    """nanoclaw IPC メッセージファイルを書き込む。"""
    timestamp_ns = int(time.time() * 1e9)
    filename = IPC_MESSAGES_DIR / f"cogito-{timestamp_ns}.json"
    payload = {
        "type": "message",
        "chatJid": chat_jid,
        "text": text,
        "groupFolder": group_folder,
    }
    IPC_MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    filename.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.3)  # ファイルウォッチャーが順序通り処理できるよう間隔を空ける


# ---------------------------------------------------------------------------
# Ollama モデルサイズチェック
# ---------------------------------------------------------------------------

def check_model_size(model_name: str, min_size_gb: float,
                     chat_jid: str, group_folder: str) -> bool:
    """Ollama API でモデルサイズを確認し、小さすぎる場合は警告してFalseを返す。"""
    ollama_host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
    url = f"{ollama_host}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        send_ipc(
            f"⚠️ Ollama API に接続できません ({url}): {e}\n"
            f"モデルチェックをスキップします。",
            chat_jid, group_folder
        )
        return True  # 接続不可の場合はチェックをスキップして続行

    models = data.get("models", [])
    # モデル名（タグなし・タグあり両方で照合）
    found = None
    for m in models:
        name = m.get("name", "")
        if name == model_name or name.split(":")[0] == model_name.split(":")[0]:
            found = m
            break

    if found is None:
        send_ipc(
            f"⚠️ モデル '{model_name}' が Ollama に見つかりません。\n"
            f"利用可能: {', '.join(m.get('name','') for m in models[:5])}",
            chat_jid, group_folder
        )
        return False

    size_bytes = found.get("size", 0)
    size_gb = size_bytes / 1e9
    if size_gb < min_size_gb:
        send_ipc(
            f"⚠️ モデル '{model_name}' のサイズが小さすぎます "
            f"({size_gb:.1f}GB < {min_size_gb}GB)。\n"
            f"空スクリプトになる可能性があります。",
            chat_jid, group_folder
        )
        return False

    return True


# ---------------------------------------------------------------------------
# スクリプト整形・送信
# ---------------------------------------------------------------------------

def format_episode_for_telegram(lines: list[str]) -> str:
    """Markdownエピソードブロックを Telegram 向けプレーンテキストに変換。"""
    result: list[str] = []
    for line in lines:
        if line.startswith("## Episode") or line.startswith("## エピソード"):
            result.append(line[3:])  # "## " を除去
            result.append("")
        elif line.startswith("### "):
            pass  # セクションヘッダー除去
        elif line.strip() in ("---", "***", "==="):
            pass  # 水平線除去
        elif line.startswith("**") and ":**" in line:
            # **Speaker:** text → Speaker: text
            result.append(line.replace("**", ""))
        elif line.startswith("*[") and line.endswith("*"):
            # *[Stage direction]* → [Stage direction]
            result.append(line[1:-1])
        else:
            result.append(line)
    return "\n".join(result).strip()


def send_script(scripts_path: Path, book_label: str, run_id: str,
                chat_jid: str, group_folder: str) -> None:
    """05_scripts.md を読み込みエピソード単位でTelegramへ送信。"""
    text = scripts_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # エピソードブロックを分割
    episodes: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if (line.startswith("## Episode") or line.startswith("## エピソード")) and current:
            episodes.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        episodes.append(current)

    # ヘッダーメッセージ
    send_ipc(
        f"📖 *Cogito完了*: {book_label}\n"
        f"Run ID: `{run_id}`\n"
        f"{'─' * 28}",
        chat_jid, group_folder
    )

    if not episodes:
        # フォールバック: 生テキストをそのまま送信
        send_ipc(text[:4000], chat_jid, group_folder)
    else:
        for ep_lines in episodes:
            ep_text = format_episode_for_telegram(ep_lines)
            if ep_text:
                send_ipc(ep_text, chat_jid, group_folder)
                time.sleep(0.5)

    # フッター
    send_ipc(
        f"✅ 完了 | Run: {run_id}\n"
        f"再実行: python3 main.py --book {resolve_book_config(book_label)} "
        f"--resume {run_id} --from-node write_scripts",
        chat_jid, group_folder
    )


def resolve_book_config(book_label: str) -> str:
    """ラベルからconfigキーを逆引き（フッター用）。"""
    for config, label in BOOK_LABELS.items():
        if label == book_label:
            return config
    return "descartes_discourse"


# ---------------------------------------------------------------------------
# エイリアス解決
# ---------------------------------------------------------------------------

def resolve_book(name: str) -> str | None:
    """ユーザー入力の書名をconfigキーに解決する。"""
    # 完全一致（小文字）
    key = name.strip().lower()
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]
    # 日本語など大文字小文字変換不要のもの
    if name.strip() in BOOK_ALIASES:
        return BOOK_ALIASES[name.strip()]
    # 部分一致（先頭一致）
    for alias, config in BOOK_ALIASES.items():
        if key.startswith(alias) or alias.startswith(key):
            return config
    return None


# ---------------------------------------------------------------------------
# メイン実行
# ---------------------------------------------------------------------------

def run(book_config: str, chat_jid: str, group_folder: str, fast: bool = True) -> int:
    """パイプラインを実行し進捗をIPC送信する。終了コードを返す。"""
    book_label = BOOK_LABELS.get(book_config, book_config)
    mode_label = "fast (~2-5分、研究スキップ)" if fast else "full (~5-15分、リサーチあり)"

    # ---------------------------------------------------------------------------
    # モデル設定の読み込み（config/ollama_models.yaml → 環境変数 → デフォルト値）
    # ---------------------------------------------------------------------------
    config_path = BOOK_RESEARCH_DIR / "config" / "ollama_models.yaml"
    reader_model_default = "llama3.2:latest"
    dramaturg_model_default = "qwen3.5:latest"
    reader_min_size_gb = 1.0
    dramaturg_min_size_gb = 4.0

    if config_path.exists() and _YAML_AVAILABLE:
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = _yaml.safe_load(f)
            if isinstance(cfg, dict):
                if "reader" in cfg and isinstance(cfg["reader"], dict):
                    reader_model_default = cfg["reader"].get("model", reader_model_default)
                    reader_min_size_gb = float(cfg["reader"].get("min_size_gb", reader_min_size_gb))
                if "dramaturg" in cfg and isinstance(cfg["dramaturg"], dict):
                    dramaturg_model_default = cfg["dramaturg"].get("model", dramaturg_model_default)
                    dramaturg_min_size_gb = float(cfg["dramaturg"].get("min_size_gb", dramaturg_min_size_gb))
        except Exception:
            pass  # 設定ファイルのパースエラーはデフォルト値にフォールバック

    reader_model = os.environ.get("COGITO_READER_MODEL", reader_model_default)
    dramaturg_model = os.environ.get("COGITO_DRAMATURG_MODEL", dramaturg_model_default)

    # ---------------------------------------------------------------------------
    # モデルサイズチェック
    # ---------------------------------------------------------------------------
    if not check_model_size(dramaturg_model, dramaturg_min_size_gb, chat_jid, group_folder):
        send_ipc(
            f"⚠️ dramaturg model '{dramaturg_model}' が小さすぎます。"
            f"空スクリプトになる可能性があります。続行します。",
            chat_jid, group_folder
        )

    # コマンド構築
    cmd = [
        sys.executable, "main.py",
        "--book", book_config,
        "--mode", "essence",
        "--skip-translate",
        "--skip-audio",
        "--reader-model", reader_model,
        "--dramaturg-model", dramaturg_model,
    ]
    if fast:
        cmd.append("--skip-research")

    # 開始通知
    send_ipc(
        f"🔬 *Cogito開始*: {book_label}\n"
        f"モード: {mode_label}",
        chat_jid, group_folder
    )

    # 環境変数設定（DockerコンテナからMacのOllamaへ接続、パッケージパス）
    env = os.environ.copy()
    env.setdefault("OLLAMA_HOST", "http://host.docker.internal:11434")
    # パッケージが /workspace/group/.pypackages にインストールされている場合は追加
    pypackages = "/workspace/group/.pypackages"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{pypackages}:{existing}" if existing else pypackages

    # サブプロセス起動
    proc = subprocess.Popen(
        cmd,
        cwd=str(BOOK_RESEARCH_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    run_dir: Path | None = None
    last_progress_time = time.time()
    last_heartbeat_time = time.time()
    start_time = time.time()

    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        now = time.time()

        # ハートビート: 2分以上進捗がなければ通知
        if now - last_heartbeat_time > 120:
            elapsed_min = int((now - start_time) / 60)
            send_ipc(f"⏳ 処理中... ({elapsed_min}分経過)", chat_jid, group_folder)
            last_heartbeat_time = now

        if not line:
            continue

        progress_sent = False

        # 進捗行をパース: [N/M] Label: summary (Xs)
        if line.startswith("[") and "/" in line and "]" in line:
            try:
                bracket_end = line.index("]")
                progress_part = line[1:bracket_end]  # "N/M"
                rest = line[bracket_end + 2:].strip()
                colon_idx = rest.find(":")
                if colon_idx != -1:
                    stage_label = rest[:colon_idx].strip()
                    summary = rest[colon_idx + 1:].strip()
                    # タイムスタンプ部分 (Xs) を削除
                    if summary.endswith(")") and "(" in summary:
                        summary = summary[:summary.rfind("(")].strip()
                    msg = f"⚙️ [{progress_part}] {stage_label}\n{summary[:120]}"
                    if now - last_progress_time > 0.5:  # 短時間の重複送信を防止
                        send_ipc(msg, chat_jid, group_folder)
                        last_progress_time = now
                        progress_sent = True
            except Exception:
                pass

        # 出力ディレクトリ検出: "  Output dir   : /path/to/run_..."
        if "Output dir" in line and "run_" in line and ":" in line:
            try:
                path_str = line.split(":", 1)[-1].strip()
                candidate = Path(path_str)
                if candidate.exists():
                    run_dir = candidate
                else:
                    # 相対パスの場合
                    run_dir = BOOK_RESEARCH_DIR / path_str
            except Exception:
                pass

        if progress_sent:
            last_heartbeat_time = now  # 進捗送信時にハートビートタイマーをリセット

    # 長時間経過した場合の通知（stdoutが閉じた後）
    total_elapsed = time.time() - start_time
    if total_elapsed > 300 and time.time() - last_progress_time > 300:
        send_ipc("⏳ Ollama推論中（時間がかかっています）", chat_jid, group_folder)

    proc.wait()

    if proc.returncode != 0:
        send_ipc(
            f"❌ Cogitoパイプラインが失敗しました (exit {proc.returncode})\n"
            f"ログ: {BOOK_RESEARCH_DIR}/logs/ を確認してください",
            chat_jid, group_folder
        )
        return proc.returncode

    # 出力ディレクトリのフォールバック: data/ 内の最新 run_* を使用
    if run_dir is None or not run_dir.exists():
        data_dir = BOOK_RESEARCH_DIR / "data"
        runs = sorted(data_dir.glob("run_*"), reverse=True)
        run_dir = runs[0] if runs else None

    if run_dir is None:
        send_ipc("❌ Cogito: 出力ディレクトリが見つかりません", chat_jid, group_folder)
        return 1

    scripts_path = run_dir / "05_scripts.md"
    if not scripts_path.exists():
        send_ipc(
            f"⚠️ Cogito: スクリプトファイルが見つかりません\n"
            f"出力ディレクトリ: {run_dir}",
            chat_jid, group_folder
        )
        return 1

    send_script(scripts_path, book_label, run_dir.name, chat_jid, group_folder)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cogito パイプラインランナー（Telegram IPC進捗通知付き）"
    )
    parser.add_argument("--book", required=True,
                        help="書名またはエイリアス（日本語・英語両対応）")
    parser.add_argument("--chat-jid", required=True,
                        help="送信先 Telegram チャットJID（例: tg:-5218254973）")
    parser.add_argument("--group-folder", default="telegram_main",
                        help="nanoclaw グループフォルダ名 (default: telegram_main)")
    parser.add_argument("--fast", action="store_true", default=True,
                        help="Fast mode: --skip-audio --skip-research（デフォルト）")
    parser.add_argument("--full", action="store_true",
                        help="Full mode: リサーチあり（--fastを無効化）")
    args = parser.parse_args()

    # --full が指定されたら fast を無効化
    fast = not args.full

    # エイリアス解決
    resolved = resolve_book(args.book)
    if resolved is None:
        print(f"❌ 不明な書名: '{args.book}'", file=sys.stderr)
        print(f"利用可能: {', '.join(sorted(set(BOOK_ALIASES.values())))}", file=sys.stderr)
        # IPC でもエラー通知
        send_ipc(AVAILABLE_BOOKS_MSG, args.chat_jid, args.group_folder)
        sys.exit(1)

    sys.exit(run(resolved, args.chat_jid, args.group_folder, fast=fast))


if __name__ == "__main__":
    main()
