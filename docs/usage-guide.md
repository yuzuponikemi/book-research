# 使い方ガイド

Project Cogito を実際に動かすための手順書。

---

## 前提条件

| 項目 | 要件 | 備考 |
|------|------|------|
| **Python** | 3.13 以上 | 3.14 で動作確認済み |
| **Ollama** | 最新版 | ローカル LLM 推論基盤 |
| **ffmpeg** | 任意のバージョン | 音声合成（`synthesize_audio`）に必要 |
| **VOICEVOX** | 任意のバージョン | 音声合成に必要。`--skip-audio` でスキップ可能 |

---

## インストール手順

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd book-research
```

### 2. Python 仮想環境のセットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 環境変数の設定

```bash
cp .env.example .env
# .env を編集して TAVILY_API_KEY を設定（Web 検索に必要）
```

`TAVILY_API_KEY` が未設定の場合、Web 検索は DuckDuckGo にフォールバックする。DuckDuckGo も利用不可の場合、研究ステージは検索結果なしで動作する。

### 4. ffmpeg のインストール（音声合成を使う場合）

```bash
# macOS
brew install ffmpeg
```

---

## Ollama モデルのセットアップ

### 必須モデル

```bash
# Reader / Director 層用（分析・構成設計）
ollama pull llama3

# Dramaturg 層用（日本語台本生成）
ollama pull qwen3-next
```

### オプションモデル

```bash
# より高品質な分析が必要な場合（18GB）
ollama pull command-r

# 翻訳ステージ用（--skip-translate でスキップ可能）
ollama pull translategemma:12b
```

### Ollama サーバーの起動

**重要**: Apple Silicon (M1/M2/M3/M4) では以下の設定で起動すること。デフォルト設定ではモデルが推論中にアンロードされ、ハングする場合がある。

```bash
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

- `OLLAMA_KEEP_ALIVE=120m` — モデルを120分間メモリに保持
- `OLLAMA_NUM_PARALLEL=1` — 並行リクエストを無効化（Apple Silicon でのデッドロック防止）

---

## VOICEVOX のセットアップ（音声合成を使う場合）

1. [VOICEVOX 公式サイト](https://voicevox.hiroshiba.jp/)からダウンロード
2. アプリケーションを起動（エンジンが `localhost:50021` で起動する）

```bash
# macOS でのアプリ起動
open -a VOICEVOX
```

動作確認:

```bash
# VOICEVOX エンジンの接続テスト
.venv/bin/python3 -m src.audio.voicevox_client --list-speakers

# テキスト→音声の動作確認
.venv/bin/python3 -m src.audio.voicevox_client "テストです" --speaker 0
```

---

## 基本的な実行方法

### essence モード（単一エピソード）

著作の核心を1つのエピソードに凝縮する。初めて試す場合に最適。

```bash
.venv/bin/python3 main.py --book descartes_discourse --mode essence
```

### curriculum モード（全6回シリーズ）

著作の全体を6回のエピソードで段階的に解説する。

```bash
.venv/bin/python3 main.py --book descartes_discourse --mode curriculum
```

### topic モード（トピック深掘り）

特定のトピックに焦点を当てた1〜2エピソード。`--topic` 引数が必須。

```bash
.venv/bin/python3 main.py --book descartes_discourse --mode topic --topic "心身二元論"
```

### 軽量実行（研究・音声・翻訳をスキップ）

テキスト分析と台本生成のみを行う。最も高速。

```bash
.venv/bin/python3 main.py --book descartes_discourse --mode essence \
    --skip-research --skip-audio --skip-translate
```

---

## 中断と再開

パイプラインは LangGraph のチェックポイント機能を使い、各ノード完了後に state を `checkpoint.sqlite` に自動保存する。これにより、長時間実行を安全に中断・再開できる。

### 中断

実行中に `Ctrl-C` で中断すると、最後に完了したノードまでの進捗が保存される。

```
[3/5] Synthesis: 6 concepts, 3 relations (45.6s)
^C
  Interrupted! Progress saved to checkpoint.
  Resume with: python3 main.py --book descartes_discourse --resume run_20260212_100013
```

### 再開（最後の checkpoint から）

```bash
.venv/bin/python3 main.py --book descartes_discourse \
    --resume run_20260212_100013
```

完了済みのノードはスキップされ、中断した箇所から実行が再開される。

### 特定ノードからの再実行

`--from-node` を使うと、指定したノード以降を再実行できる。以前のノードの結果は checkpoint から復元される。

```bash
# 台本だけを再生成（分析・設計の結果はそのまま利用）
.venv/bin/python3 main.py --book descartes_discourse \
    --resume run_20260212_100013 \
    --from-node write_scripts

# モデルを変更して台本を再生成
.venv/bin/python3 main.py --book descartes_discourse \
    --resume run_20260212_100013 \
    --from-node write_scripts \
    --dramaturg-model command-r
```

`--from-node` で指定可能なノード名：

```
ingest, analyze_chunks, synthesize, research, critique, enrich,
generate_reading_material, plan, write_scripts, synthesize_audio,
check_translate, translate
```

---

## CLI 引数一覧

| 引数 | デフォルト | 説明 |
|------|-----------|------|
| `--book` | `descartes_discourse` | 書籍設定名（`config/books/` 内のファイル名、拡張子なし） |
| `--mode` | `essence` | エピソード設計モード: `essence` / `curriculum` / `topic` |
| `--persona` | `descartes_default` | ペルソナプリセット名（`config/personas.yaml` 内のキー） |
| `--topic` | なし | `topic` モード時の焦点トピック（topic モードでは必須） |
| `--reader-model` | `llama3` | Reader/Director 層の Ollama モデル名 |
| `--dramaturg-model` | `qwen3-next` | Dramaturg 層の Ollama モデル名 |
| `--translator-model` | `translategemma:12b` | 翻訳ステージの Ollama モデル名 |
| `--skip-research` | `false` | 研究・批評・統合・読書ガイドをスキップ |
| `--skip-audio` | `false` | VOICEVOX 音声合成をスキップ |
| `--skip-translate` | `false` | 日本語翻訳をスキップ |
| `--resume` | なし | 前回の実行を再開する（run ID を指定、例: `run_20260212_100013`） |
| `--from-node` | なし | 指定ノードから再実行する（`--resume` 必須） |
| `--trace` | `false` | Arize Phoenix のローカル UI を起動し、全 LLM 呼び出しをトレース |

---

## LLM トレーシング（Arize Phoenix）

`--trace` フラグを付けると、ローカルに Arize Phoenix UI が起動し、全 LLM 呼び出し（ChatOllama 経由）の入出力・レイテンシをリアルタイムで可視化できる。

```bash
.venv/bin/python3 main.py --book descartes_discourse --mode essence --trace
```

起動後、ターミナルに表示される URL（通常 `http://localhost:6006`）をブラウザで開くと、各ステージ（analyst, synthesizer, planner 等）のスパンがトレースとして表示される。

**依存パッケージ**: `arize-phoenix`, `openinference-instrumentation-langchain`（`requirements.txt` に含まれている）

---

## 設定ファイル

### 書籍設定: `config/books/<name>.yaml`

新しい本を追加するには、このディレクトリに YAML ファイルを作成する。

```yaml
# config/books/my_book.yaml

book:
  title: "Meditations on First Philosophy"   # 必須: 英語タイトル
  title_ja: "省察"                            # 任意: 日本語タイトル（未指定時は title と同じ）
  author: "René Descartes"                    # 必須: 著者名
  author_ja: "ルネ・デカルト"                   # 任意: 日本語著者名
  year: 1641                                  # 任意: 出版年

source:
  type: "gutenberg"                           # 必須: "gutenberg" | "local_file" | "url"
  url: "https://gutenberg.org/cache/epub/XXX/pgXXX.txt"
  cache_filename: "pgXXX.txt"                 # data/ 以下にキャッシュ

chunking:
  strategy: "regex"                           # 必須: "regex" | "chapter" | "heading" | "token"
  pattern: "^(MEDITATION\\s+(?:I{1,3}|IV|V|VI))\\b"  # regex 戦略の場合に必要

research:
  search_queries:                             # テンプレート変数 {author}, {title} 等が利用可能
    - "{author} {title} historical context"
    - "{author} biography philosophical life"
    - "{title} critical reception philosophy"
  reference_files:                            # ローカル参考文献（data/ からの相対パス）
    - "data/my-reference.md"
  max_search_results: 5                       # クエリあたりの最大検索結果数

context:
  era: "17th century"                         # 時代
  tradition: "Rationalism"                    # 哲学的伝統
  key_terms:                                  # チャンク分析時に探すべき用語
    - "Hyperbolic Doubt"
    - "Evil Genius"
    - "Wax Argument"
  notable_critics:                            # 批評ステージで参照する批評家
    - name: "Arnauld"
      perspective: "Pointed out the Cartesian Circle"
    - name: "Gassendi"
      perspective: "Criticized from empiricist standpoint"

prompt_fragments:
  work_description: >                         # LLM プロンプトで使われる作品の一行説明
    Descartes' "Meditations" (1641) is a systematic attempt to establish
    certain knowledge through radical doubt.
  analysis_guidance: >                        # 分析時の追加指示
    Pay attention to: the six Meditations' progressive structure,
    the role of God in validating clear and distinct ideas.
```

必須フィールド: `book.title`, `book.author`, `source.type`, `chunking.strategy`

テンプレート変数: 検索クエリとプロンプト断片で `{author}`, `{title}`, `{author_ja}`, `{title_ja}`, `{year}` が使用可能。

### ペルソナ設定: `config/personas.yaml`

```yaml
presets:
  my_preset:
    persona_a:
      name: "Student"          # 台本中の話者名
      role: "哲学初心者"         # 役割の説明
      description: "..."        # キャラクターの詳細
      tone: "素直・驚き"         # トーン
      speaking_style: "..."     # 話し方の特徴
    persona_b:
      name: "Mentor"
      role: "哲学の案内人"
      description: "..."
      tone: "穏やか・ソクラテス的"
      speaking_style: "..."
    voice:                       # VOICEVOX スピーカー ID マッピング
      Student: 2                 # 春日部つむぎ
      Mentor: 3                  # 雨晴はう
      _default_a: 2              # フォールバック（persona_a）
      _default_b: 3              # フォールバック（persona_b）
```

既存のプリセット:

| プリセット名 | persona_a | persona_b | 特徴 |
|-------------|-----------|-----------|------|
| `descartes_default` | Host（現代の懐疑論者） | Descartes（哲学者の亡霊） | 時代を超えた直接対話 |
| `socratic` | Student（哲学初心者） | Mentor（哲学の案内人） | 問いを通じた発見的学習 |
| `debate` | Advocate（著者の擁護者） | Critic（批判的検証者） | 弁証法的対立 |

---

## 出力ファイルの読み方

実行完了後、出力は `data/run_YYYYMMDD_HHMMSS/` に保存される。

| ファイル | 内容 | 読み方 |
|---------|------|--------|
| `01_chunks.md` | テキストチャンク一覧 | テキストがどう分割されたかを確認 |
| `02_chunk_analyses.md` | チャンク別の概念・アポリア・論証 | 各チャンクから何が抽出されたかを確認 |
| `03_concept_graph.md` | 統合コンセプトグラフ | 著作全体の知的構造を俯瞰 |
| `03b_research_context.md` | 研究文脈 | Web 検索と参考文献から得られた背景情報 |
| `03c_critique_report.md` | 批評レポート | 各概念に対する歴史的批判 |
| `03d_enriched_context.md` | 統合コンテキスト | 英日2言語の研究要約 |
| `03e_reading_material.md` | 包括的読書ガイド | ポッドキャストの補助教材として利用可能 |
| `04_syllabus.md` | エピソード計画 | 各エピソードのテーマ・概念・認知的ブリッジ |
| `05_scripts.md` | 対話台本 | 最終成果物。ポッドキャストの台本全文 |
| `06_audio/ep01.mp3` ... | 音声ファイル | VOICEVOX で合成されたポッドキャスト音声 |
| `*_ja.md` | 日本語翻訳版 | 英語中間出力の日本語版 |
| `checkpoint.sqlite` | チェックポイント | `--resume` での再開に使用 |

`.json` ファイルは同じデータの機械読み取り可能な版で、後続の分析や可視化に利用できる。

LLM コールのログは `logs/run_YYYYMMDD_HHMMSS.json` に保存される。詳細は [log-format-guide.md](log-format-guide.md) を参照。

---

## よくあるトラブルと対処法

### Ollama がハングする / レスポンスが返ってこない

**原因**: モデルが推論中にアンロードされた（特に `command-r` のような大型モデル）。

**対処法**:

```bash
# Ollama を以下の設定で再起動
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

### JSON パースエラーが頻発する

**原因**: 小さなモデル（llama3 等）が JSON 形式に従わない出力を返している。

**対処法**:
- `ChatOllama` で `format="json"` が設定されていることを確認（Reader 層では設定済み）
- より大きなモデル（`command-r`）を `--reader-model command-r` で指定
- `extract_json()` がコードフェンスやテキストプリアンブル付き JSON を処理するので、軽微なフォーマット違反は自動修正される

### VOICEVOX に接続できない

**原因**: VOICEVOX Engine が起動していない。

**対処法**:

```bash
# VOICEVOX アプリを起動
open -a VOICEVOX

# 接続確認
curl http://localhost:50021/version
```

VOICEVOX が起動していない場合、`--skip-audio` で音声合成をスキップできる。パイプラインの他のステージは正常に動作する。

### pydub / audioop 関連のエラー（Python 3.13+）

**原因**: Python 3.13 で `audioop` モジュールが標準ライブラリから削除された。

**対処法**:

```bash
pip install audioop-lts
```

`requirements.txt` に既に含まれているが、仮想環境を再作成した場合は再インストールが必要。

### Web 検索が動作しない

**原因**: `TAVILY_API_KEY` が未設定で、DuckDuckGo も利用不可。

**対処法**:

```bash
# Tavily の場合（高品質、有料）
export TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx

# DuckDuckGo の場合（無料）
pip install ddgs
```

Web 検索が完全に利用不可の場合でも、`--skip-research` でスキップするか、検索結果なしでパイプラインを実行できる（品質は低下する）。

### メモリ不足

**原因**: 大型モデル（`qwen3-next` は 50GB）がメモリを大量に消費する。

**対処法**:
- Dramaturg 層のモデルをより小さなモデルに変更: `--dramaturg-model llama3`（品質は低下する）
- Reader 層も小さなモデルで十分: `--reader-model llama3`

---

## パフォーマンス目安

以下は Apple Silicon Mac（M1/M2/M3/M4 系）での目安。実際の所要時間はモデルサイズ、テキスト量、チャンク数に依存する。

| ステージ | essence モード | curriculum モード | 備考 |
|---------|---------------|-----------------|------|
| Ingest | 数秒 | 数秒 | 初回のみダウンロード |
| Analyze | 5〜15分 | 5〜15分 | チャンク数 x LLM コール |
| Synthesize | 2〜5分 | 2〜5分 | 1回の LLM コール |
| Research | 1〜3分 | 1〜3分 | Web 検索 + 参考文献要約 |
| Critique | 2〜5分 | 2〜5分 | 1回の LLM コール |
| Enrich | 2〜5分 | 2〜5分 | 1回の LLM コール |
| Reading Material | 10〜20分 | 10〜20分 | チャンク数 + 2 の LLM コール |
| Plan | 1〜3分 | 1〜3分 | 1回の LLM コール |
| Script | 3〜10分 | 15〜60分 | エピソード数 x LLM コール |
| Audio | 3〜10分 | 15〜30分 | VOICEVOX 逐次合成 |
| Translate | 5〜15分 | 5〜15分 | セクション数 x LLM コール |

**最速パス**（essence + 全スキップ）:

```bash
.venv/bin/python3 main.py --mode essence --skip-research --skip-audio --skip-translate
# → 約 15〜30分
```

**フルパイプライン**（curriculum + 全ステージ）:

```bash
.venv/bin/python3 main.py --mode curriculum
# → 約 60〜180分（中断しても --resume で再開可能）
```
