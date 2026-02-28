# 使い方ガイド v2 — マイクロサービス構成

Project Cogito のマイクロサービス版（`cogito/` パッケージ）の実行方法。

> [!NOTE]
> 旧パイプライン（`python main.py`）は引き続き動作します。新旧は並行して共存しています。

---

## 前提条件

| 項目 | 要件 |
|---|---|
| **Python** | 3.13 以上 |
| **Ollama** | 最新版（ローカル LLM） |
| **VOICEVOX** | 音声合成を使う場合のみ |
| **ffmpeg** | 音声合成を使う場合のみ |

### 必須 Ollama モデル

```bash
# 分析・計画用（Reader）
ollama pull llama3

# 台本生成用（Dramaturg）
ollama pull qwen3-next
```

### Ollama の起動（Apple Silicon の場合）

```bash
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

### 環境変数

```bash
cp .env.example .env
# TAVILY_API_KEY を設定（Web検索に使用。未設定時は DuckDuckGo にフォールバック）
```

---

## ① Orchestrator — ワンコマンド実行（推奨）

`python -m cogito.orchestrator` が最もシンプルな方法。内部でルートを自動選択する。

### Route A（本文テキストあり）

```bash
# essence モード（単一エピソード）
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode essence

# curriculum モード（全6回シリーズ）
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode curriculum \
    --persona socratic

# topic モード（テーマ絞り込み）
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode topic --topic "心身二元論"
```

### Route B（Web検索 — 本文なし、本丸）

```bash
# 書籍設定ファイルがある場合
python -m cogito.orchestrator \
    --source web \
    --book descartes_discourse \
    --mode essence

# 任意のテーマ・著者を指定する場合
python -m cogito.orchestrator \
    --source web \
    --subject "ニーチェ ツァラトゥストラはこう言った" \
    --mode curriculum
```

### 既存の ConceptGraph から再開

```bash
# 分析済みの concept_graph.json をそのまま使って Syllabus+Scripts を生成
python -m cogito.orchestrator \
    --from-graph data/run_xxx/03_concept_graph.json \
    --mode topic --topic "方法論的懐疑"
```

### Orchestrator CLI オプション一覧

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--source` | `book` | `book`（Route A）/ `web`（Route B） |
| `--book` | — | Book config 名（`config/books/` 内のファイル名、拡張子なし） |
| `--subject` | — | 自由形式のテーマ（Route B かつ book config がない場合） |
| `--from-graph` | — | 既存 ConceptGraphV1 JSON のパス（分析をスキップ） |
| `--mode` | `essence` | `essence` / `curriculum` / `topic` |
| `--topic` | — | topic モードで必須 |
| `--persona` | `descartes_default` | ペルソナプリセット名 |
| `--reader-model` | `llama3` | 分析・計画用 Ollama モデル |
| `--dramaturg-model` | `qwen3-next` | 台本生成用 Ollama モデル |
| `--translator-model` | `translategemma:12b` | 翻訳用 Ollama モデル |
| `--skip-translate` | `false` | 日本語翻訳をスキップ |
| `--skip-audio` | `false` | VOICEVOX 音声合成をスキップ |

---

## ② 各サービスを個別実行（細かく制御したい場合）

### Step 1: Ingestor（Route A のみ）

本文テキストを取得してチャンク化する。

```bash
python -m cogito.services.ingestor \
    --book descartes_discourse \
    --output data/run_xxx/01_chunks.json
```

| 引数 | 説明 |
|---|---|
| `--book` | Book config 名 |
| `--output` | 出力 JSON パス |

### Step 2a: Analyst（Route A のみ）

ChunksV1 → ConceptGraphV1。

```bash
python -m cogito.services.analyst \
    --input  data/run_xxx/01_chunks.json \
    --output data/run_xxx/03_concept_graph.json \
    --model  llama3
```

| 引数 | 説明 |
|---|---|
| `--input` | `01_chunks.json` のパス |
| `--output` | ConceptGraphV1 JSON の出力先 |
| `--model` | Ollama モデル名（デフォルト: `llama3`） |

### Step 2b: WebResearcher（Route B）

Web 検索から直接 ConceptGraphV1 を生成する。

```bash
# Book config がある場合（見出しや検索クエリを設定から取得）
python -m cogito.services.web_researcher \
    --book   descartes_discourse \
    --output data/run_xxx/03_concept_graph.json

# 任意のテーマを指定する場合（LLMが見出しを推定）
python -m cogito.services.web_researcher \
    --subject "カント 純粋理性批判" \
    --author  "イマヌエル・カント" \
    --output  data/run_xxx/03_concept_graph.json \
    --model   llama3
```

| 引数 | 説明 |
|---|---|
| `--book` | Book config 名（省略可） |
| `--subject` | テーマ文字列（`--book` がない場合に使用） |
| `--author` | 著者名（省略可） |
| `--output` | ConceptGraphV1 JSON の出力先 |
| `--model` | Ollama モデル（デフォルト: `llama3`） |

WebResearcher の内部処理:

```
planner    → list[Heading]          見出しを決定（設定 or LLM 推定）
searcher   → dict[id → results]     見出しごとにクエリ生成 → Web 検索
aggregator → list[SynthesizedChunk] 検索結果を LLM で段落に要約
synthesizer→ ConceptGraphV1         SYNTHESIS_PROMPT で概念グラフ生成
```

### Step 3: Producer

ConceptGraphV1 → SyllabusV1 + list[ScriptV1]。

```bash
python -m cogito.services.producer \
    --input  data/run_xxx/03_concept_graph.json \
    --output data/run_xxx/ \
    --mode   essence \
    --persona descartes_default \
    --planner-model   llama3 \
    --dramaturg-model qwen3-next

# curriculum モード
python -m cogito.services.producer \
    --input  data/run_xxx/03_concept_graph.json \
    --output data/run_xxx/ \
    --mode   curriculum \
    --book   descartes_discourse      # タイトル・著者メタデータ取得用（省略可）

# topic モード
python -m cogito.services.producer \
    --input  data/run_xxx/03_concept_graph.json \
    --output data/run_xxx/ \
    --mode   topic --topic "方法論的懐疑"
```

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--input` | — | ConceptGraphV1 JSON パス |
| `--output` | — | 出力ディレクトリ（`04_syllabus.json`, `05_scripts.json` が生成される） |
| `--mode` | `essence` | `essence` / `curriculum` / `topic` |
| `--topic` | — | topic モードで必須 |
| `--persona` | `descartes_default` | ペルソナプリセット |
| `--planner-model` | `llama3` | シラバス生成モデル |
| `--dramaturg-model` | `qwen3-next` | 台本生成モデル |
| `--book` | — | タイトル/著者メタデータ取得用（省略可） |

---

## ③ 既存パイプライン（main.py）との連携

新サービスで生成した `03_concept_graph.json` を既存パイプラインの続きから実行できる。

```bash
# 手順 1: WebResearcherで概念グラフを生成
python -m cogito.services.web_researcher \
    --book descartes_discourse \
    --output data/run_20260228_160000/03_concept_graph.json

# 手順 2: 既存 main.py でその先を実行（音声合成まで）
python main.py --book descartes_discourse \
    --resume run_20260228_160000 \
    --from-node plan
```

---

## 出力ファイル構成

```
data/run_YYYYMMDD_HHMMSS/
├── 01_chunks.json          ← ChunksV1 (Ingestor 出力 / Route A のみ)
├── 03_concept_graph.json   ← ConceptGraphV1 (Analyst or WebResearcher 出力)
├── 04_syllabus.json        ← SyllabusV1 (Producer 出力)
├── 05_scripts.json         ← list[ScriptV1] (Producer 出力)
├── 06_audio/               ← 音声ファイル（既存 main.py が生成）
│   ├── ep01.mp3
│   └── ...
└── checkpoint.sqlite       ← LangGraph チェックポイント（main.py 用）
```

---

## 設定ファイル

### 書籍設定: `config/books/<name>.yaml`

```yaml
book:
  title: "Discourse on the Method"
  title_ja: "方法序説"
  author: "René Descartes"
  author_ja: "ルネ・デカルト"
  year: 1637

source:
  type: "gutenberg"   # gutenberg | local_file | url | arxiv
  url: "https://www.gutenberg.org/cache/epub/59/pg59.txt"
  cache_filename: "pg59.txt"

chunking:
  strategy: "regex"   # regex | chapter | heading | token
  pattern: "^(PART\\s+[IVX]+)\\b"   # regex の場合

research:
  search_queries:
    - "{author} {title} historical context"
    - "{author} biography philosophical life"
  headings:                    # WebResearcher の見出し（省略時は LLM 推定）
    - id: "overview"
      title: "Descartes and the Discourse on the Method"
    - id: "cogito"
      title: "Cogito ergo sum — I think therefore I am"

context:
  era: "17th century"
  key_terms: ["Methodical Doubt", "Cogito", "Mind-Body Dualism"]

prompt_fragments:
  work_description: >
    Descartes' "Discourse on the Method" (1637), the founding text of modern rationalism.
```

### ペルソナ設定: `config/personas.yaml`

```yaml
presets:
  my_preset:
    persona_a:
      name: "Host"
      role: "現代の哲学ジャーナリスト"
      description: "批判的思考を持ち、現代の問題と哲学を結びつける"
      tone: "好奇心旺盛・鋭い"
      speaking_style: "短い質問で相手に考えさせる"
    persona_b:
      name: "Descartes"
      role: "哲学者の亡霊"
      description: "17世紀の哲学者として現代に問いかける"
      tone: "論理的・慎重"
      speaking_style: "演繹的に、ゆっくりと論を展開する"
    voice:
      Host: 2        # VOICEVOX スピーカーID
      Descartes: 3
```

既存のプリセット:

| プリセット名 | persona_a | persona_b |
|---|---|---|
| `descartes_default` | Host（現代の懐疑論者） | Descartes（哲学者の亡霊） |
| `socratic` | Student（哲学初心者） | Mentor（哲学の案内人） |
| `debate` | Advocate（著者の擁護者） | Critic（批判的検証者） |

---

## よくあるトラブル

### Ollama がハングする

```bash
# 正しい起動コマンド（Apple Silicon 必須）
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

### Web 検索が動作しない

```bash
# Tavily の設定
export TAVILY_API_KEY=tvly-xxxxx

# DuckDuckGo のインストール（無料フォールバック）
pip install ddgs
```

Tavily も DuckDuckGo も使えない場合でも、WebResearcher は LLM のみで動作する（品質は低下）。

### JSON パースエラーが頻発する

```bash
# より大きなモデルを使用
python -m cogito.orchestrator --reader-model command-r ...
```

### ペルソナが見つからない

```bash
# 利用可能なプリセットを確認
python -c "
import yaml
with open('config/personas.yaml') as f:
    cfg = yaml.safe_load(f)
print(list(cfg['presets'].keys()))
"
```

### 個別サービスのインポートテスト

```bash
python -c "
from cogito.services.ingestor import ingest_from_book_config
from cogito.services.analyst import extract_all_chunks, synthesize_concept_graph
from cogito.services.producer import plan_syllabus, write_podcast_scripts
from cogito.services.web_researcher.planner import plan_headings
print('All service imports OK')
"
```

---

## モデル選択ガイド

| 用途 | 推奨モデル | 最小モデル | 備考 |
|---|---|---|---|
| 分析・計画 (Reader) | `command-r` (18GB) | `llama3` (4.7GB) | 大きいほど概念抽出品質が高い |
| 台本生成 (Dramaturg) | `qwen3-next` (50GB) | `llama3` (4.7GB) | Qwen 系は日本語が得意 |
| 翻訳 | `translategemma:12b` | — | `--skip-translate` でスキップ可 |

---

## パフォーマンス目安（Apple Silicon）

| フェーズ | Route A | Route B |
|---|---|---|
| Ingestor | 数十秒 | — |
| Analyst / WebResearcher | 15〜30分 | 10〜25分 |
| Producer (essence) | 5〜15分 | 〈同左〉 |
| Producer (curriculum × 6) | 30〜90分 | 〈同左〉 |
