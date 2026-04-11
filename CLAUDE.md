# Project Cogito (book-research)

書籍・Webリサーチ → 概念グラフ生成 → ポッドキャスト台本 → 音声合成 の LangGraph パイプライン。

**最終更新: 2026-03-30**

---

## 現在の状態

🟢 稼働中。基本パイプラインは完成。Telegram連携スキルも実装済み。

---

## パス

- プロジェクトルート: `/workspace/group/book-research/`
- 詳細な状況: `PROJECT_STATUS.md`

---

## 技術スタック

- Python 3.11（uv/venv）
- LangGraph + SQLite チェックポインティング
- ローカル Ollama モデル（`http://host.docker.internal:11434`）
- VOICEVOX（音声合成）
- nanoclaw IPC（Telegram配信）

---

## よく使うコマンド

```bash
cd /workspace/group/book-research
source .venv/bin/activate

# パイプライン実行（書籍モード）
python main.py --book descartes_discourse

# Telegram配信付きで実行（/cogito スキル経由）
python run_pipeline.py --book descartes --chat-jid tg:-5218254973 --fast

# 中断した実行を再開
python main.py --resume run_YYYYMMDD_HHMMSS

# デフォルトモデル（2026-03-30 変更）
# --reader-model glm-4.7-flash:latest
# --dramaturg-model glm-4.7-flash:latest
```

---

## パイプライン構成

```
Route A (書籍テキスト):
  Book Config YAML → [Ingestor] → ChunksV1 → [Analyst] → ConceptGraphV1 ─┐
                                                                            ├→ [Producer] → Syllabus + Scripts
Route B (Webリサーチ):                                                      │
  Subject / Author → [WebResearcher] → ConceptGraphV1 ─────────────────────┘

後処理:
  Scripts → [Audio] → MP3 (VOICEVOX)
  Outputs → [Translator] → *_ja.md
```

---

## モデル構成

| 役割 | 現在のデフォルト | 代替 |
|------|----------------|------|
| 分析（`--reader-model`） | `glm-4.7-flash:latest` | `command-r` 18GB |
| 台本生成（`--dramaturg-model`） | `glm-4.7-flash:latest` | `qwen3` 50GB |
| 翻訳（`--translator-model`） | `translategemma:12b` | — |

---

## 出力ディレクトリ構成

```
data/run_YYYYMMDD_HHMMSS/
  01_chunks.json           ← ChunksV1
  02_chunk_analyses.json   ← 概念抽出（並列処理、max_workers=4）
  03_concept_graph.json    ← ConceptGraphV1
  04_syllabus.json         ← SyllabusV1
  05_scripts.json          ← list[ScriptV1]
  06_audio/                ← MP3
data/checkpoints.db        ← LangGraph チェックポイント
```

---

## 設定ファイル

- `config/books/*.yaml` — 書籍設定
- `config/personas.yaml` — キャラクター設定
- 利用可能なペルソナ: `descartes_default`, `socratic`, `debate`

---

## 直近の変更（2026-03-30）

- `extractor.py`: `extract_all_chunks()` に `ThreadPoolExecutor(max_workers=4)` 並列化を追加
- `cli.py`: デフォルトモデルを `glm-4.7-flash:latest` に変更
- `run_pipeline.py`: Telegram IPC 配信付きランナーを追加
- `/home/node/.claude/skills/cogito/SKILL.md`: `/cogito` スキルを追加

---

## 既知の問題・ハマりポイント

- thinking モデル（qwen3/qwq/deepseek-r1）使用時のみ `format="json"` を適用（他は不要）
- uv は新セッション起動時に `/home/node/.local/bin/uv` が必要（PATH未設定の場合は再インストール）

---

## 次にやること

1. Telegram連携の実運用テスト（`/cogito デカルト` コマンド）
2. 教科書モード（`--mode curriculum`）の品質確認
3. 中国語 → 日本語翻訳モデルの評価

---

## 参考ドキュメント

- `PIPELINE.md` / `PIPELINE_ja.md` — クイックスタート
- `docs/architecture-v2.md` — 設計・スキーマ・データフロー
- `idea.md` — 拡張アイデア集
