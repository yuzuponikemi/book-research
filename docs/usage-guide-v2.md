# 使い方ガイド — cogito パッケージ

Project Cogito の実行方法・設定・運用ガイド。

---

## 前提条件

| 項目 | 要件 |
|---|---|
| **Python** | 3.13 以上（3.14 推奨） |
| **Ollama** | 最新版（ローカル LLM） |
| **VOICEVOX** | 音声合成を使う場合のみ |
| **ffmpeg** | 音声合成を使う場合のみ |

### 必須 Ollama モデル

```bash
ollama pull llama3          # 分析・計画用（Reader）
ollama pull qwen3-next      # 台本生成用（Dramaturg）
```

### Ollama の起動（Apple Silicon）

```bash
# 並列実行禁止・KEEP_ALIVE 必須（ハング防止）
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

### 環境変数

```bash
cp .env.example .env
# TAVILY_API_KEY を設定（Web 検索に使用。未設定時は DuckDuckGo にフォールバック）
```

---

## ① Orchestrator — ワンコマンド実行（推奨）

### Route A（本文テキストあり）

```bash
# essence モード（単一エピソード）
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode essence

# curriculum モード（連続シリーズ）
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode curriculum \
    --persona socratic

# topic モード（テーマ絞り込み）
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode topic --topic "心身二元論"

# 音声・翻訳をスキップして高速実行
python -m cogito.orchestrator \
    --book descartes_discourse \
    --mode essence \
    --skip-audio --skip-translate
```

### Route B（Web 検索）

```bash
# Book config がある場合（見出しや検索クエリを設定から取得）
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
# 分析済みの concept_graph.json をそのまま使って Syllabus + Scripts を生成
python -m cogito.orchestrator \
    --from-graph data/run_xxx/03_concept_graph.json \
    --mode topic --topic "方法論的懐疑"
```

### 中断したランを再開

```bash
# LangGraph チェックポイントから再開
python -m cogito.orchestrator \
    --resume run_20260301_120000
```

### Orchestrator CLI オプション一覧

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--source` | `book` | `book`（Route A）/ `web`（Route B） |
| `--book` | — | Book config 名（`config/books/` 内のファイル名、拡張子なし） |
| `--subject` | — | 自由形式のテーマ（Route B かつ book config がない場合） |
| `--from-graph` | — | 既存 ConceptGraphV1 JSON のパス（分析をスキップ） |
| `--resume` | — | 再開する run_id（例: `run_20260301_120000`） |
| `--mode` | `essence` | `essence` / `curriculum` / `topic` |
| `--topic` | — | `topic` モードで必須 |
| `--persona` | `descartes_default` | ペルソナプリセット名 |
| `--reader-model` | `llama3` | 分析・計画用 Ollama モデル |
| `--dramaturg-model` | `qwen3-next` | 台本生成用 Ollama モデル |
| `--translator-model` | `translategemma:12b` | 翻訳用 Ollama モデル |
| `--skip-research` | `false` | Web 検索ステージをスキップ |
| `--skip-translate` | `false` | 日本語翻訳をスキップ |
| `--skip-audio` | `false` | VOICEVOX 音声合成をスキップ |

---

## ② 各サービスを個別実行

### Ingestor（Route A のみ）

```bash
python -m cogito.services.ingestor \
    --book descartes_discourse \
    --output data/run_xxx/01_chunks.json
```

| 引数 | 説明 |
|---|---|
| `--book` | Book config 名 |
| `--output` | 出力 JSON パス |

### Analyst（Route A のみ）

```bash
python -m cogito.services.analyst \
    --input  data/run_xxx/01_chunks.json \
    --output data/run_xxx/03_concept_graph.json \
    --model  llama3

# Book config を指定して key_terms を提供する場合
python -m cogito.services.analyst \
    --input  data/run_xxx/01_chunks.json \
    --output data/run_xxx/03_concept_graph.json \
    --book   descartes_discourse
```

| 引数 | 説明 |
|---|---|
| `--input` | `01_chunks.json` のパス |
| `--output` | ConceptGraphV1 JSON の出力先 |
| `--model` | Ollama モデル名（デフォルト: `llama3`） |
| `--book` | key_terms 取得用（省略可） |

### WebResearcher（Route B）

```bash
# Book config がある場合
python -m cogito.services.web_researcher \
    --book   descartes_discourse \
    --output data/run_xxx/03_concept_graph.json

# 任意のテーマを指定する場合
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

**Web 検索テスト:**
```bash
python -m cogito.services.web_researcher.web_search --engine auto "Descartes Cogito"
```

### Producer

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
    --book   descartes_discourse   # タイトル・著者メタデータ取得用（省略可）

# topic モード
python -m cogito.services.producer \
    --input  data/run_xxx/03_concept_graph.json \
    --output data/run_xxx/ \
    --mode   topic --topic "方法論的懐疑"
```

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--input` | — | ConceptGraphV1 JSON パス |
| `--output` | — | 出力ディレクトリ（`04_syllabus.json`, `05_scripts.json` が生成） |
| `--mode` | `essence` | `essence` / `curriculum` / `topic` |
| `--topic` | — | `topic` モードで必須 |
| `--persona` | `descartes_default` | ペルソナプリセット |
| `--planner-model` | `llama3` | シラバス生成モデル |
| `--dramaturg-model` | `qwen3-next` | 台本生成モデル |
| `--book` | — | タイトル/著者メタデータ取得用（省略可） |

---

## ③ 出力ファイル構成

```
data/run_YYYYMMDD_HHMMSS/
├── 01_chunks.json          ← ChunksV1（Route A のみ）
├── 02_chunk_analyses.json  ← チャンク別概念抽出（Route A のみ）
├── 03_concept_graph.json   ← ConceptGraphV1（両ルート）
├── 04_syllabus.json        ← SyllabusV1
├── 05_scripts.json         ← list[ScriptV1]
├── 06_audio/               ← MP3 ファイル群（--skip-audio でなければ）
│   ├── ep01.mp3
│   └── ...
├── 06_audio.json           ← 音声合成メタデータ
├── 02_chunk_analyses_ja.md ← 日本語翻訳（--skip-translate でなければ）
├── 03_concept_graph_ja.md
└── 04_syllabus_ja.md

data/checkpoints.db         ← LangGraph SQLite チェックポイント（--resume 用）
logs/run_YYYYMMDD_HHMMSS.json  ← 思考ログ（全 LLM プロンプト・レスポンス）
```

---

## ④ 設定ファイル

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
  strategy: "regex"
  pattern: "^(PART\\s+[IVX]+)\\b"

research:
  search_queries:
    - "{author} {title} historical context"
    - "{author} biography philosophical life"
  headings:                         # WebResearcher の見出し（省略時は LLM 推定）
    - id: "overview"
      title: "Descartes and the Discourse on the Method"
    - id: "cogito"
      title: "Cogito ergo sum — I think therefore I am"

context:
  era: "17th century"
  key_terms: ["Methodical Doubt", "Cogito", "Mind-Body Dualism"]
  notable_critics: ["Gilbert Ryle", "Princess Elisabeth of Bohemia"]

prompt_fragments:
  work_description: >
    Descartes' "Discourse on the Method" (1637), the founding text of modern rationalism.
```

**source.type の選択肢:**

| type | 動作 |
|---|---|
| `gutenberg` | Project Gutenberg から URL でダウンロード（キャッシュあり） |
| `local_file` | `data/` 以下のローカルファイル（`source.path` に相対パス） |
| `url` | 任意の URL |
| `arxiv` | arXiv 論文 ID を指定してフルテキスト取得（`source.arxiv_id`） |

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
      Host: 2         # VOICEVOX スピーカー ID
      Descartes: 3
      _default_a: 2   # フォールバック
      _default_b: 3
```

既存のプリセット:

| プリセット名 | persona_a | persona_b |
|---|---|---|
| `descartes_default` | Host（現代の懐疑論者） | Descartes（哲学者の亡霊） |
| `socratic` | Student（哲学初心者） | Mentor（哲学の案内人） |
| `debate` | Advocate（著者の擁護者） | Critic（批判的検証者） |

---

## ⑤ よくあるトラブル

### Ollama がハングする

```bash
# 正しい起動コマンド（Apple Silicon 必須）
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

ChatOllama に `timeout=` を設定しないこと（ハングの原因）。並列実行も禁止。

### Web 検索が動作しない

```bash
# Tavily の設定
export TAVILY_API_KEY=tvly-xxxxx

# DuckDuckGo のインストール（無料フォールバック）
pip install ddgs

# 検索エンジンのテスト
python -m cogito.services.web_researcher.web_search --engine auto "Descartes"
```

### JSON パースエラーが頻発する

```bash
# より大きなモデルを使用
python -m cogito.orchestrator --reader-model command-r ...
```

### relation_type バリデーションエラー

LLM が `'related_to'` など enum 外の値を返すことがある（既知の問題）。
ConceptGraphV1 スキーマは `depends_on | contradicts | evolves_into` のみ許可。
発生した場合、ランを再試行するか、`synthesizer.py` の `from_legacy_dict` で事前にフィルタリングする。

### VOICEVOX に接続できない

```bash
open -a VOICEVOX   # macOS の場合
# または VOICEVOX Engine バイナリを直接起動
```

ポート 50021 で起動確認: `curl http://localhost:50021/version`

### ペルソナが見つからない

```bash
python -c "
import yaml
with open('config/personas.yaml') as f:
    cfg = yaml.safe_load(f)
print(list(cfg['presets'].keys()))
"
```

### インポート確認

```bash
python -c "
from cogito.config.book_config import load_book_config
from cogito.utils.logger import create_step, extract_json
from cogito.schemas import ConceptGraphV1, ChunksV1, SyllabusV1
from cogito.services.ingestor.adapters.book import ingest_from_book_config
from cogito.services.analyst.extractor import extract_all_chunks
from cogito.services.producer.planner import plan_syllabus
print('All imports OK')
"
```

---

## ⑥ モデル選択ガイド

| 用途 | 推奨モデル | 最小モデル | 備考 |
|---|---|---|---|
| 分析・計画（Reader） | `command-r` 18GB | `llama3` 4.7GB | 大きいほど概念抽出品質が高い |
| 台本生成（Dramaturg） | `qwen3-next` 50GB | `llama3` 4.7GB | Qwen 系は日本語が得意 |
| 翻訳 | `translategemma:12b` | — | `--skip-translate` でスキップ可 |

---

## ⑦ パフォーマンス目安（Apple Silicon）

| フェーズ | Route A | Route B |
|---|---|---|
| Ingestor | 数十秒 | — |
| Analyst / WebResearcher | 15〜30分 | 10〜25分 |
| Producer (essence) | 5〜15分 | 〈同左〉 |
| Producer (curriculum × 6) | 30〜90分 | 〈同左〉 |
| Audio (essence) | 5〜15分 | 〈同左〉 |
| Translate | 5〜20分 | 〈同左〉 |
