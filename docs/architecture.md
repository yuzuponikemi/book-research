# パイプラインアーキテクチャ

哲学テキストを分析し、日本語ポッドキャスト台本・音声を自動生成するパイプライン。

```
                          Project Cogito — データフロー

  ┌─────────┐   ┌──────────┐   ┌───────────┐
  │ Ingest  │──▶│ Analyze  │──▶│ Synthesize│──┐
  │ (取込)  │   │ (分析)   │   │ (合成)    │  │
  └─────────┘   └──────────┘   └───────────┘  │
  Stage 1       Stage 2        Stage 3        │
  テキスト取得   チャンク別      統合コンセプト  │
  & チャンク化   概念抽出        グラフ生成      │
                                               │
       ┌───────────────────────────────────────┘
       │  --skip-research で 3b〜3e をスキップ可能
       ▼
  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
  │ Research │──▶│ Critique │──▶│ Enrich   │──▶│ Reading  │
  │ (研究)   │   │ (批評)   │   │ (統合)   │   │ Material │
  └──────────┘   └──────────┘   └──────────┘   └──────────┘
  Stage 3b       Stage 3c       Stage 3d       Stage 3e
  Web検索 +      歴史的批判      EN/JA要約      包括的
  参考文献       の生成          の統合         読書ガイド
       │
       └─────────────────────────────────────────┐
                                                  │
  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──┴───────┐
  │ Plan     │──▶│ Script   │──▶│ Audio    │──▶│ Translate│
  │ (設計)   │   │ (台本)   │   │ (音声)   │   │ (翻訳)   │
  └──────────┘   └──────────┘   └──────────┘   └──────────┘
  Stage 4        Stage 5        Stage 6        Stage 7
  エピソード      日本語対話      VOICEVOX       中間出力の
  構成設計        台本生成        音声合成        日本語翻訳
```

---

## ステージ詳細

### Stage 1: テキスト取り込み（Ingest）

| 項目 | 内容 |
|------|------|
| **入力** | 書籍設定ファイル (`config/books/<name>.yaml`) |
| **処理** | テキスト取得（Gutenberg/ローカル/URL） → ボイラープレート除去 → チャンク分割 |
| **出力** | `state["raw_chunks"]` — テキストチャンクのリスト |
| **保存** | `01_chunks.json`, `01_chunks.md` |
| **ソース** | `src/reader/ingestion.py` |

テキスト取得元は `source.type` で指定する:

- `gutenberg` — Project Gutenberg からダウンロード（ヘッダー/フッター自動除去）
- `local_file` — ローカルファイルから読み込み
- `url` — 任意の URL からダウンロード

チャンク分割戦略は `chunking.strategy` で指定する:

- `regex` — 正規表現パターンでセクション分割（例: `^(PART\s+(?:I{1,3}|IV|V|VI))\b`）
- `chapter` — `Chapter N` / `Chapter IV` 等のヘッダーで分割
- `heading` — マークダウン見出し or 全大文字見出しで分割
- `token` — 語数ベースで段落境界に沿って等分割（デフォルト 2000 語）

取得したテキストは `data/<cache_filename>` にキャッシュされ、2回目以降はダウンロードをスキップする。

---

### Stage 2: チャンク分析（Analyze）

| 項目 | 内容 |
|------|------|
| **入力** | `state["raw_chunks"]` |
| **処理** | 各チャンクを LLM に投入し、7次元の構造を抽出 |
| **出力** | `state["chunk_analyses"]` — チャンクごとの分析結果リスト |
| **保存** | `02_chunk_analyses.json`, `02_chunk_analyses.md` |
| **ソース** | `src/reader/analyst.py` |
| **モデル** | Reader モデル（`--reader-model`、デフォルト: `llama3`）、temperature=0.1、format="json" |

各チャンクから以下の7次元を抽出する:

1. **概念（Concepts）**: 哲学的概念 — ID、名前、詳細な説明、原著からの引用、出典チャンク
2. **アポリア（Aporias）**: 未解決の哲学的緊張 — 問い、文脈、関連概念
3. **関係（Relations）**: 概念間の依存関係 — `depends_on` / `contradicts` / `evolves_into`
4. **論理の流れ（Logic Flow）**: 著者の推論過程の叙述的要約
5. **論証構造（Arguments）**: 前提・結論・論証タイプ（演繹/帰納/類推）
6. **名前付き哲学的手法（Named Moves）**: 方法的懐疑、コギトなど既知の技法
7. **修辞的戦略（Rhetorical Strategies）**: 隠喩、類推、思考実験、権威への訴え

チャンクは**逐次処理**される（Ollama は Apple Silicon 上で並行リクエストに非対応のため）。各チャンクの処理にはタイムアウト付きリトライ（最大3回）が組み込まれている。

---

### Stage 3: 概念グラフ合成（Synthesize）

| 項目 | 内容 |
|------|------|
| **入力** | `state["chunk_analyses"]` |
| **処理** | 全チャンクの分析結果を統合し、重複を除去した概念グラフを構築 |
| **出力** | `state["concept_graph"]` — 統合された概念グラフ |
| **保存** | `03_concept_graph.json`, `03_concept_graph.md` |
| **ソース** | `src/reader/synthesizer.py` |
| **モデル** | Reader モデル、temperature=0.1、format="json" |

合成で行われる処理:

- **概念の重複排除**: 同一概念をマージ（目標: 10〜20概念）
- **クロスチャンク関係の構築**: 部をまたがる概念の依存関係を検出（目標: 8〜12関係）
- **コア・フラストレーション**: 著作全体を貫く根本的な知的緊張の特定
- **アポリアの保全**: 重複のみマージし、固有の緊張は保持（目標: 4〜8アポリア）
- **統合ロジックフロー**: 全体を通じた推論の連鎖の叙述

出力は `ConceptGraph` Pydantic モデルでバリデーションされる。

---

### Stage 3b: 研究（Research）

| 項目 | 内容 |
|------|------|
| **入力** | `state["book_config"]`（検索クエリ、参考文献パス） |
| **処理** | Web 検索 + 参考文献ファイルの要約 → 統合リサーチコンテキスト |
| **出力** | `state["research_context"]` — 構造化された研究文脈 |
| **保存** | `03b_research_context.json`, `03b_research_context.md` |
| **ソース** | `src/researcher/researcher.py`, `src/researcher/web_search.py`, `src/researcher/reference_loader.py` |
| **スキップ** | `--skip-research` |

処理の流れ:

1. **Web 検索**: 書籍設定の `research.search_queries` をバッチ実行（Tavily 優先、DuckDuckGo フォールバック）
2. **参考文献の読み込みと要約**: `research.reference_files` で指定された `.md` / `.txt` ファイルを LLM で要約
3. **統合**: Web 検索結果 + 参考文献要約を LLM で以下の5カテゴリに整理:
   - `author_biography` — 著者の伝記
   - `historical_context` — 歴史的文脈
   - `publication_history` — 出版の経緯
   - `critical_reception` — 批判的受容
   - `modern_significance` — 現代的意義

---

### Stage 3c: 批評（Critique）

| 項目 | 内容 |
|------|------|
| **入力** | `state["concept_graph"]`, `state["research_context"]`, 書籍設定の `context.notable_critics` |
| **処理** | 各概念に対する歴史的批判・反論・現代的再解釈を生成 |
| **出力** | `state["critique_report"]` — 概念別の批評レポート |
| **保存** | `03c_critique_report.json`, `03c_critique_report.md` |
| **ソース** | `src/critic/critic.py` |
| **スキップ** | `--skip-research` |

書籍設定ファイルの `context.notable_critics` に指定された批評家（例: パスカル、ヒューム、カント、アルノー、ガッサンディ、ライプニッツ）の視点を活用し、以下を生成する:

- 概念ごとの歴史的批判（批評家名・時代付き）
- 反論（著者またはその擁護者による応答）
- 現代的再解釈
- 未解決の学術的論争
- 包括的な学術論争（`overarching_debates`）
- 受容の叙述（`reception_narrative`）

---

### Stage 3d: 統合（Enrich）

| 項目 | 内容 |
|------|------|
| **入力** | `state["research_context"]`, `state["critique_report"]` |
| **処理** | 研究文脈 + 批評を英日2言語の要約に統合 |
| **出力** | `state["enrichment"]` — EN/JA 要約 + 批判的視点 |
| **保存** | `03d_enriched_context.json`, `03d_enriched_context.md` |
| **ソース** | `src/director/enricher.py` |
| **スキップ** | `--skip-research` |

3つの要約を生成する:

- `enrichment_summary` — 英語（800〜1200語）
- `enrichment_summary_ja` — 日本語（1500〜2500字）
- `critique_perspectives_ja` — 日本語の批判的視点トーキングポイント（400〜800字）

これらは Stage 4（Plan）と Stage 5（Script）に注入される。

---

### Stage 3e: 読書ガイド（Reading Material）

| 項目 | 内容 |
|------|------|
| **入力** | パイプライン全ステージの出力（概念グラフ、分析、研究、批評、統合） |
| **処理** | Gemini Deep Research スタイルの包括的学習ガイドを生成 |
| **出力** | `state["reading_material"]` — マークダウンドキュメント |
| **保存** | `03e_reading_material.md` |
| **ソース** | `src/researcher/reading_material.py` |
| **スキップ** | `--skip-research` |

以下の構成で生成される:

1. **アブストラクト** — 著作の概要（日本語、400〜600語）
2. **章ごとの詳細分析** — 各部の概要、主要概念、論証構造、修辞的技法、批判的考察
3. **総合的結論** — 著者の革命的貢献、批判的受容、現代的意義
4. **参考文献** — Web ソース + ローカル参考文献

各章の分析には、該当部に歴史的に関連する批評家の視点が注入される。

---

### Stage 4: エピソード設計（Plan）

| 項目 | 内容 |
|------|------|
| **入力** | `state["concept_graph"]`, `state["enrichment"]`（あれば）, モード設定 |
| **処理** | モードに応じたエピソード構成（シラバス）を設計 |
| **出力** | `state["syllabus"]` — エピソード計画 |
| **保存** | `04_syllabus.json`, `04_syllabus.md` |
| **ソース** | `src/director/planner.py` |
| **モデル** | Reader モデル、temperature=0.3、format="json" |

3つのモード:

| モード | エピソード数 | 説明 |
|--------|-------------|------|
| `essence` | 1 | 著作の核心となるアポリア1つに焦点を当てた単一エピソード |
| `curriculum` | 6 | 著作の論理的進行に沿った全6回のシリーズ |
| `topic` | 1〜2 | 指定されたトピックに関連する概念を抽出した深掘りエピソード |

各エピソードには以下の要素が含まれる:

- `title` — エピソードタイトル
- `theme` — 中心テーマ
- `concept_ids` — カバーする概念ID（概念グラフ参照）
- `aporia_ids` — 扱うアポリアID
- `cognitive_bridge` — 現代との接点（AI、SNS、スタートアップ等）
- `cliffhanger` — 次回への問い

enrichment が利用可能な場合、歴史的文脈と批判的視点がプロンプトに追加される。

---

### Stage 5: 台本生成（Script）

| 項目 | 内容 |
|------|------|
| **入力** | `state["syllabus"]`, `state["concept_graph"]`, `state["persona_config"]`, `state["enrichment"]` |
| **処理** | 各エピソードについて、2人の登場人物による日本語対話台本を生成 |
| **出力** | `state["scripts"]` — エピソードごとの台本リスト |
| **保存** | `05_scripts.json`, `05_scripts.md` |
| **ソース** | `src/dramaturg/scriptwriter.py` |
| **モデル** | Dramaturg モデル（`--dramaturg-model`、デフォルト: `qwen3-next`）、temperature=0.7 |

台本は3幕構成:

1. **第1幕: 導入と問題提起**（約3分 / 15〜20発言）— 現代の具体的シナリオから哲学的問いを引き出す
2. **第2幕: 哲学的掘り下げ**（約5分 / 20〜30発言）— 原著の概念を掘り下げ、引用を織り込む
3. **第3幕: 統合と余韻**（約2分 / 10〜15発言）— 一段高い視点でまとめ、問いを残す

品質基準: 合計50〜65発言、全て日本語、各発言1〜4文。

ペルソナは `config/personas.yaml` から読み込まれ、2人の登場人物の名前・役割・トーン・話し方が台本プロンプトに反映される。

---

### Stage 6: 音声合成（Audio）

| 項目 | 内容 |
|------|------|
| **入力** | `state["scripts"]`, `state["persona_config"]` |
| **処理** | VOICEVOX Engine で台本を音声合成し、MP3 にエクスポート |
| **出力** | `state["audio_metadata"]` — エピソードごとの音声メタデータ |
| **保存** | `06_audio/ep01.mp3`, ..., `06_audio.json`, `06_audio.md` |
| **ソース** | `src/audio/synthesizer.py`, `src/audio/voicevox_client.py` |
| **スキップ** | `--skip-audio` |

VOICEVOX Engine（`localhost:50021`）に対して HTTP 経由で音声合成を行う。各登場人物にはペルソナ設定の `voice` マッピングで VOICEVOX スピーカー ID が割り当てられる。

音声生成の流れ:

1. Opening bridge をナレーター音声で合成
2. 各対話行を話者に応じた音声で逐次合成
3. Closing hook をナレーター音声で合成
4. 話者交代時・セクション間に無音を挿入
5. pydub で結合し、MP3（192kbps）にエクスポート

無音の長さ:
- 同一話者: 600ms
- 話者交代: 800ms
- セクション境界: 1800ms

---

### Stage 7: 翻訳（Translate）

| 項目 | 内容 |
|------|------|
| **入力** | 英語の中間出力ファイル（`02_chunk_analyses.md`, `03_concept_graph.md`, `04_syllabus.md`） |
| **処理** | TranslateGemma で日本語に翻訳 |
| **出力** | `*_ja.md` ファイル |
| **保存** | `02_chunk_analyses_ja.md`, `03_concept_graph_ja.md`, `04_syllabus_ja.md` |
| **ソース** | `src/translator.py` |
| **モデル** | Translator モデル（`--translator-model`、デフォルト: `translategemma:12b`） |
| **スキップ** | `--skip-translate` |

長いマークダウンドキュメントはセクション（`##` / `###` ヘッダー）単位で分割し、チャンクごとに翻訳する（TranslateGemma のコンテキスト長制約への対応、1チャンク最大3000文字）。

---

## 共有 State 辞書のスキーマ

パイプライン全体で単一の `state` 辞書が受け渡される。各ステージは必要なキーを読み取り、新しいキーを追加して返す。

```python
state = {
    # メタデータ
    "book_title": str,           # 書籍タイトル
    "book_config": dict,         # 書籍設定（config/books/<name>.yaml の内容）
    "mode": str,                 # "essence" | "curriculum" | "topic"
    "topic": str | None,         # topic モード時のトピック指定
    "persona_config": dict,      # ペルソナ設定
    "reader_model": str,         # Reader/Director 層のモデル名
    "dramaturg_model": str,      # Dramaturg 層のモデル名

    # Stage 1
    "raw_chunks": list[str],     # テキストチャンクのリスト

    # Stage 2
    "chunk_analyses": list[dict],# チャンクごとの分析結果

    # Stage 3
    "concept_graph": dict,       # 統合コンセプトグラフ

    # Stage 3b
    "research_context": dict,    # Web検索 + 参考文献の統合結果

    # Stage 3c
    "critique_report": dict,     # 概念別の批評レポート

    # Stage 3d
    "enrichment": dict,          # EN/JA 要約と批判的視点

    # Stage 3e  (reading_material は直接ファイル保存)

    # Stage 4
    "syllabus": dict,            # エピソード計画

    # Stage 5
    "scripts": list[dict],       # エピソードごとの台本

    # Stage 6
    "audio_metadata": list[dict],# 音声メタデータ

    # ログ
    "thinking_log": list[dict],  # 全LLMコールのプロンプト/レスポンス記録
}
```

---

## 出力ディレクトリ構成

各実行は `data/run_YYYYMMDD_HHMMSS/` に保存される。

```
data/run_20250210_143000/
├── 01_chunks.json              # テキストチャンク（機械読み取り用）
├── 01_chunks.md                # テキストチャンク（人間読み取り用）
├── 02_chunk_analyses.json      # チャンク別分析結果
├── 02_chunk_analyses.md        # チャンク別分析レポート
├── 02_chunk_analyses_ja.md     # 〃 日本語版（Stage 7）
├── 03_concept_graph.json       # 統合コンセプトグラフ
├── 03_concept_graph.md         # 統合コンセプトグラフレポート
├── 03_concept_graph_ja.md      # 〃 日本語版（Stage 7）
├── 03b_research_context.json   # リサーチ結果（Stage 3b）
├── 03b_research_context.md     # リサーチレポート
├── 03c_critique_report.json    # 批評レポート（Stage 3c）
├── 03c_critique_report.md      # 批評レポート
├── 03d_enriched_context.json   # 統合コンテキスト（Stage 3d）
├── 03d_enriched_context.md     # 統合コンテキストレポート
├── 03e_reading_material.md     # 包括的読書ガイド（Stage 3e）
├── 04_syllabus.json            # エピソード計画
├── 04_syllabus.md              # エピソード計画レポート
├── 04_syllabus_ja.md           # 〃 日本語版（Stage 7）
├── 05_scripts.json             # 対話台本
├── 05_scripts.md               # 対話台本レポート
├── 06_audio/                   # 音声ファイル（Stage 6）
│   ├── ep01.mp3
│   ├── ep02.mp3
│   └── ...
└── 06_audio.json               # 音声メタデータ
```

LLM コールのログは別途 `logs/run_YYYYMMDD_HHMMSS.json` に保存される。各ステップのプロンプト・レスポンス・パース結果・エラーが全て記録されており、デバッグやトレーサビリティに利用できる。

---

## ソースコード構成

```
project-root/
├── main.py                          # CLI エントリポイント、パイプライン実行
├── requirements.txt                 # Python 依存パッケージ
├── .env.example                     # 環境変数テンプレート
│
├── config/
│   ├── personas.yaml                # ペルソナプリセット定義
│   └── books/
│       └── descartes_discourse.yaml # 書籍設定（デカルト方法序説）
│
├── src/
│   ├── models.py                    # Pydantic モデル定義（ConceptGraph, Syllabus, Script 等）
│   ├── logger.py                    # 思考ログシステム、JSON 抽出ユーティリティ
│   ├── book_config.py               # 書籍設定 YAML ローダー（バリデーション、テンプレート解決）
│   ├── translator.py                # Stage 7: TranslateGemma による日本語翻訳
│   │
│   ├── reader/                      # Reader 層（テキスト分析）
│   │   ├── ingestion.py             #   Stage 1: テキスト取得・チャンク分割
│   │   ├── analyst.py               #   Stage 2: チャンク別概念抽出
│   │   └── synthesizer.py           #   Stage 3: 概念グラフ合成
│   │
│   ├── researcher/                  # Researcher 層（外部情報収集）
│   │   ├── web_search.py            #   Tavily / DuckDuckGo 検索エンジン
│   │   ├── reference_loader.py      #   参考文献ファイルの読み込み・要約
│   │   ├── researcher.py            #   Stage 3b: 研究コンテキスト統合
│   │   └── reading_material.py      #   Stage 3e: 包括的読書ガイド生成
│   │
│   ├── critic/
│   │   └── critic.py                # Stage 3c: 歴史的批判の生成
│   │
│   ├── director/                    # Director 層（構成設計）
│   │   ├── enricher.py              #   Stage 3d: 研究+批評の統合
│   │   └── planner.py               #   Stage 4: エピソード設計
│   │
│   ├── dramaturg/                   # Dramaturg 層（台本生成）
│   │   └── scriptwriter.py          #   Stage 5: 日本語対話台本生成
│   │
│   └── audio/                       # Audio 層（音声合成）
│       ├── voicevox_client.py       #   VOICEVOX Engine HTTP クライアント
│       └── synthesizer.py           #   Stage 6: 台本→MP3 変換
│
├── data/                            # データ（テキストキャッシュ、実行出力）
│   ├── pg59.txt                     #   Project Gutenberg キャッシュ
│   └── run_YYYYMMDD_HHMMSS/        #   各実行の出力ディレクトリ
│
└── logs/                            # LLM コールログ
    └── run_YYYYMMDD_HHMMSS.json     #   実行ごとの全プロンプト/レスポンス記録
```
