# Project Cogito — パイプラインガイド

> English version: [PIPELINE.md](PIPELINE.md)

## クイックスタート

```bash
# 仮想環境を有効化
source .venv/bin/activate

# Ollama 起動（Apple Silicon）
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve

# 実行: 本文テキスト → ポッドキャスト台本
python -m cogito.orchestrator --book descartes_discourse --mode essence

# 実行: Web検索 → ポッドキャスト台本（本文不要）
python -m cogito.orchestrator --source web --subject "ニーチェ ツァラトゥストラはこう言った" --mode curriculum

# 中断したランを再開
python -m cogito.orchestrator --resume run_20260301_120000
```

---

## アーキテクチャ概要

2つの入力ルートが Producer で合流するパイプラインです。

```
Route A（本文テキストあり）:
  Book Config YAML → [Ingestor]      → ChunksV1
                   → [Analyst]       → ConceptGraphV1 ─┐
                                                        ├→ [Producer] → Syllabus + Scripts
Route B（Web検索）:                                     │
  テーマ / 著者    → [WebResearcher] → ConceptGraphV1 ─┘

後処理（両ルート共通）:
  Scripts → [Audio]      → MP3 ファイル（VOICEVOX）
  出力    → [Translator] → *_ja.md ファイル
```

全体のオーケストレーションは **LangGraph** (`cogito/orchestrator/graph.py`) が担い、SQLite チェックポイントによる途中再開が可能です。
各サービスは `cogito/services/` 内の独立モジュールです。

---

## CLIオプション

| フラグ | デフォルト | 説明 |
|---|---|---|
| `--book BOOK` | — | Book config 名（`--subject` と排他） |
| `--subject TEXT` | — | 自由形式のテーマ（Route B、book config なし） |
| `--from-graph PATH` | — | 分析をスキップ、既存の ConceptGraphV1 JSON から開始 |
| `--resume RUN_ID` | — | 中断したランをチェックポイントから再開 |
| `--source` | `book` | `book`（Route A）/ `web`（Route B） |
| `--mode` | `essence` | `essence`（1話）/ `curriculum`（3-6話）/ `topic`（特定テーマ） |
| `--topic TEXT` | — | `topic` モード時に必須 |
| `--persona` | `descartes_default` | `config/personas.yaml` のペルソナプリセット名 |
| `--reader-model` | `llama3` | 分析・計画用 Ollama モデル |
| `--dramaturg-model` | `qwen3-next` | 日本語台本生成用 Ollama モデル |
| `--translator-model` | `translategemma:12b` | EN→JA 翻訳用 Ollama モデル |
| `--skip-research` | — | Web 検索ステージをスキップ（Route A のみ） |
| `--skip-audio` | — | VOICEVOX 音声合成をスキップ |
| `--skip-translate` | — | 日本語翻訳をスキップ |

---

## パイプラインの各ステージ

### ステージ 1: テキスト取得（Route A のみ）

`cogito/services/ingestor/` が Book Config の `source` 設定に従いテキストを取得し、チャンクに分割します。

| source.type | 動作 |
|---|---|
| `gutenberg` | Project Gutenberg からダウンロード（キャッシュあり） |
| `local_file` | `data/` 以下のローカルファイルを読み込み |
| `url` | 任意の URL から取得 |
| `arxiv` | arXiv 論文を ar5iv HTML 経由でフルテキスト取得 |

出力: `01_chunks.json`（`ChunksV1` スキーマ）

**LLM 呼び出し: なし**（決定論的なテキスト処理）

---

### ステージ 2a: 概念抽出（Route A）

`cogito/services/analyst/extractor.py` が各チャンクを Reader モデルで分析し、以下を抽出します。

- **概念（concepts）**: 名前・定義・原文引用（チャンクごとに3-8個）
- **アポリア（aporias）**: 未解決の問い・矛盾
- **関係（relations）**: 概念間の依存・矛盾・発展
- **論証構造（argument_structures）**
- **修辞戦略（rhetorical_strategies）**

続いて `analyst/synthesizer.py` が全チャンクの分析を統合し、`ConceptGraphV1` を生成します（重複概念の統合、チャンク横断の関係構築）。

出力: `02_chunk_analyses.json` → `03_concept_graph.json`

**確認ポイント（`03_concept_graph.json`）:**
- `core_frustration` は汎用的な要約ではなく真の知的緊張を表しているか
- `logic_flow` はテキスト全体の一貫した物語を語っているか
- チャンク間で重複する概念が正しく統合されているか

---

### ステージ 2b: Web リサーチ（Route B）

`cogito/services/web_researcher/` が4ステップで ConceptGraphV1 を生成します。

```
Planner    → list[Heading]           見出しを決定（設定 or LLM 推定）
Searcher   → dict[id → results]      各見出しでクエリ生成 → Web 検索
Aggregator → list[SynthesizedChunk]  検索結果を LLM で段落要約
Synthesizer→ ConceptGraphV1          概念グラフ生成
```

Web 検索エンジン:
- **Tavily**（`TAVILY_API_KEY` 設定時、高品質）
- **DuckDuckGo**（フォールバック、API キー不要、`pip install ddgs`）

出力: `03_concept_graph.json`（Route A と同一スキーマ）

---

### ステージ 3: 制作（Producer）

`cogito/services/producer/` が2ステップで台本を生成します。

**Planner**: `ConceptGraphV1` → `SyllabusV1`

| モード | エピソード数 | 説明 |
|---|---|---|
| `essence` | 1話 | 核心的な緊張を捉える |
| `curriculum` | 3-6話 | アイデアの論理的進行に沿って展開 |
| `topic` | 1-2話 | `--topic` で指定したテーマに集中 |

**Podcast**: `SyllabusV1` → `list[ScriptV1]`

各エピソードは3幕構成（50-65発言を目標）:
1. **導入** — 現代の具体例から哲学的問いを引き出す
2. **掘り下げ** — 原著の概念を丁寧に展開し、引用を織り込む
3. **統合と余韻** — 議論をまとめ、次エピソードへの期待を高める

出力: `04_syllabus.json`、`05_scripts.json`

---

### ステージ 4: 音声合成（Audio）

`cogito/services/audio/` が VOICEVOX Engine（localhost:50021）を使って各エピソードの MP3 を生成します。

- ペルソナの `voice` マッピング（`config/personas.yaml`）でスピーカー ID を解決
- 同一スピーカー間: 600ms 無音、話者交代: 800ms 無音、セクション区切り: 1800ms 無音
- ビットレート: 192kbps MP3

VOICEVOX が起動していない場合はスキップされます（エラーにはなりません）。

出力: `06_audio/ep01.mp3` ... / `06_audio.json`

---

### ステージ 5: 日本語翻訳（Translator）

`cogito/services/translator/` が英語で生成された中間出力を TranslateGemma 12B で日本語に翻訳します。

翻訳対象:
- `02_chunk_analyses.md` → `02_chunk_analyses_ja.md`
- `03_concept_graph.md` → `03_concept_graph_ja.md`
- `04_syllabus.md` → `04_syllabus_ja.md`

> 台本（`05_scripts.json`）は最初から日本語で生成されるため翻訳対象外です。

---

## 出力ファイル構成

```
data/run_YYYYMMDD_HHMMSS/
  01_chunks.json               ← ChunksV1（Route A のみ）
  02_chunk_analyses.json       ← チャンク別概念抽出（Route A のみ）
  03_concept_graph.json        ← ConceptGraphV1（両ルート）
  04_syllabus.json             ← SyllabusV1（エピソード計画）
  05_scripts.json              ← list[ScriptV1]（対話台本）
  06_audio/                    ← MP3 ファイル（--skip-audio でなければ）
    ep01.mp3 ...
  06_audio.json                ← 音声合成メタデータ
  02_chunk_analyses_ja.md      ← 日本語翻訳（--skip-translate でなければ）
  03_concept_graph_ja.md
  04_syllabus_ja.md

data/checkpoints.db            ← LangGraph SQLite チェックポイント（--resume 用）
logs/run_YYYYMMDD_HHMMSS.json  ← 思考ログ（全 LLM プロンプト・レスポンス）
```

---

## サービスの個別実行

各サービスは独立して実行できます（部分的な再実行やデバッグに有用）。

```bash
# Ingestor: Book config → ChunksV1
python -m cogito.services.ingestor \
    --book descartes_discourse \
    --output data/run_xxx/01_chunks.json

# Analyst: ChunksV1 → ConceptGraphV1
python -m cogito.services.analyst \
    --input  data/run_xxx/01_chunks.json \
    --output data/run_xxx/03_concept_graph.json

# WebResearcher: テーマ → ConceptGraphV1
python -m cogito.services.web_researcher \
    --subject "カント 純粋理性批判" \
    --author  "イマヌエル・カント" \
    --output  data/run_xxx/03_concept_graph.json

# Producer: ConceptGraphV1 → Syllabus + Scripts
python -m cogito.services.producer \
    --input  data/run_xxx/03_concept_graph.json \
    --output data/run_xxx/ \
    --mode   curriculum \
    --persona descartes_default

# Web 検索テスト
python -m cogito.services.web_researcher.web_search --engine auto "Descartes Cogito"
```

---

## モデル選択ガイド

| 用途 | 推奨モデル | 最小要件 | 備考 |
|---|---|---|---|
| 分析・計画（`--reader-model`） | `command-r` 18GB | `llama3` 4.7GB | 大きいほど概念抽出品質が向上 |
| 台本生成（`--dramaturg-model`） | `qwen3-next` 50GB | `llama3` 4.7GB | Qwen 系は日本語に優れる |
| 翻訳（`--translator-model`） | `translategemma:12b` | — | `--skip-translate` でスキップ可 |

**注意:**
- `format="json"` が Reader モデルに必須（JSON 構造を確実に返させるため）
- 台本生成は JSON を含む自由形式テキストのため JSON モード強制なし
- Planner（計画）は English 出力を使用（LLM の日本語 JSON 生成が不安定なため）。日本語版は翻訳ステージで生成

---

## ペルソナ設定

`config/personas.yaml` でキャラクターと VOICEVOX スピーカー ID を定義します。

| プリセット名 | persona_a | persona_b | スタイル |
|---|---|---|---|
| `descartes_default` | Host（現代の懐疑論者） | Descartes（哲学者の亡霊） | 現代的アナロジーで哲学を語る |
| `socratic` | Student（哲学初心者） | Mentor（哲学の案内人） | ソクラテス式問答法 |
| `debate` | Advocate（著者の擁護者） | Critic（批判的検証者） | 弁証法的な激しい議論 |

---

## 思考ログ（デバッグ用）

`logs/run_YYYYMMDD_HHMMSS.json` に全 LLM 呼び出しが記録されます。

```json
{
  "timestamp": "2026-03-01T10:00:00.000000",
  "layer": "analyst",
  "node": "extractor",
  "action": "analyze_chunk:PART IV",
  "input_summary": "Chunk 'PART IV': 15597 chars",
  "llm_prompt": "You are a philosopher ...",
  "llm_raw_response": "{ \"concepts\": [...] }",
  "parsed_output": { "concepts": [...] },
  "error": null,
  "reasoning": "Extracted 5 concepts, 1 aporias, 3 relations from PART IV"
}
```

**概念が欠落している場合のデバッグ手順:**
1. `02_chunk_analyses.json` でチャンクレベルで抽出されていたか確認
2. 抽出されていた → `synthesizer` ステップの `llm_raw_response` を確認（統合時に消された可能性）
3. 抽出されていない → `extractor` ステップの `llm_raw_response` を確認（JSON 解析失敗の可能性）

---

## よくあるトラブル

| 症状 | 原因 | 対策 |
|---|---|---|
| 概念が 0 個のチャンクがある | LLM の JSON 出力が不正 | 思考ログの `llm_raw_response` を確認 |
| コンセプトグラフの概念が少ない | モデルが小さすぎる | `--reader-model command-r` を使用 |
| Ollama がハングする | Apple Silicon での並列実行問題 | `OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve` |
| `relation_type` バリデーションエラー | LLM が enum 外の値を返した | 想定済み既知の問題（`'related_to'` 等を返すことがある） |
| VOICEVOX に接続できない | エンジンが起動していない | `open -a VOICEVOX` でエンジンを起動 |
| Web 検索が動作しない | API キー未設定 | `.env` に `TAVILY_API_KEY=tvly-xxx` を追加 |

---

## 詳細ドキュメント

- [アーキテクチャ](docs/architecture-v2.md) — サービス設計、スキーマ、データフロー
- [使い方ガイド](docs/usage-guide-v2.md) — 完全な CLI リファレンス、設定例
- [データスキーマ](docs/data-schema-reference.md) — Pydantic スキーマの詳細
- [デバッグガイド](docs/debugging-guide.md) — LLM 呼び出しのトレースと問題解決
