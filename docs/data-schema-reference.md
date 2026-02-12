# データスキーマリファレンス

パイプラインの各ステージで生成される中間データの JSON スキーマ。
デバッグ時に「この段階のデータが正しいか」を判断するための基準となる。

---

## 目次

1. [CogitoState（パイプライン全体の状態）](#cogitostate)
2. [Stage 1: raw_chunks](#stage-1-raw_chunks)
3. [Stage 2: chunk_analyses](#stage-2-chunk_analyses)
4. [Stage 3: concept_graph](#stage-3-concept_graph)
5. [Stage 3b: research_context](#stage-3b-research_context)
6. [Stage 3c: critique_report](#stage-3c-critique_report)
7. [Stage 3d: enrichment](#stage-3d-enrichment)
8. [Stage 3e: reading_material](#stage-3e-reading_material)
9. [Stage 4: syllabus](#stage-4-syllabus)
10. [Stage 5: scripts](#stage-5-scripts)
11. [Stage 6: audio_metadata](#stage-6-audio_metadata)
12. [thinking_log（LLM コールログ）](#thinking_log)

---

## CogitoState

`src/models.py` で定義される `TypedDict`。LangGraph の state としてパイプライン全体を通じて受け渡される。

```python
class CogitoState(TypedDict):
    # 設定（初期化時に固定）
    book_config: dict           # 書籍設定 YAML の全内容
    book_title: str             # 例: "Discourse on the Method"
    mode: str                   # "essence" | "curriculum" | "topic"
    topic: str | None           # topic モード時のみ（例: "心身二元論"）
    persona_config: dict        # ペルソナプリセットの dict
    reader_model: str           # 例: "llama3", "command-r"
    dramaturg_model: str        # 例: "qwen3-next"
    translator_model: str       # 例: "translategemma:12b"
    work_description: str       # LLM プロンプト用の一行説明
    run_dir: str                # 出力ディレクトリの絶対パス（str: Path は serialize 不可）
    run_id: str                 # 例: "run_20260212_100013"

    # フラグ
    skip_research: bool
    skip_audio: bool
    skip_translate: bool

    # データ成果物（各ステージで更新）
    raw_chunks: list[str]       # → Stage 1
    chunk_analyses: list[dict]  # → Stage 2
    concept_graph: dict         # → Stage 3
    research_context: dict      # → Stage 3b
    critique_report: dict       # → Stage 3c
    enrichment: dict            # → Stage 3d
    reading_material: str       # → Stage 3e（Markdown 文字列）
    syllabus: dict              # → Stage 4
    scripts: list[dict]         # → Stage 5
    audio_metadata: list[dict]  # → Stage 6

    # ログ
    thinking_log: list[dict]    # 全 LLM コールの記録（ThinkingStep の dict 表現）
```

---

## Stage 1: raw_chunks

**ソース**: `src/reader/ingestion.py` → `ingest()`
**state キー**: `raw_chunks`
**ファイル**: `01_chunks.json`

### 型

```
list[str]
```

テキストチャンクの文字列リスト。各要素はテキストの一部分。

### 例

```json
[
  "PART I\n\nGood sense is, of all things among men, the most equally distributed...",
  "PART II\n\nI was then in Germany, attracted thither by the wars...",
  "PART III\n\nAnd finally, as it is not enough, before commencing to rebuild...",
  "PART IV\n\nI do not know that I ought to tell you...",
  "PART V\n\nI would here willingly have proceeded...",
  "PART VI\n\nThree years have now elapsed since I finished the Treatise..."
]
```

### バリデーション基準

| チェック項目 | 期待値 |
|-------------|--------|
| 配列長 | 通常 4〜8（regex 分割時） |
| 各要素の文字数 | 数千〜数万文字 |
| 空文字列 | 含まれないこと |

### よくある問題

- **チャンク数が 1**: regex パターンがテキストにマッチしていない → `chunking.pattern` を確認
- **チャンク数が 0**: テキスト取得に失敗（ネットワークエラー、キャッシュ破損）

---

## Stage 2: chunk_analyses

**ソース**: `src/reader/analyst.py` → `analyze_chunks()`
**state キー**: `chunk_analyses`
**ファイル**: `02_chunk_analyses.json`

### 型

```
list[dict]  # 各 dict は ChunkAnalysis の構造
```

### ChunkAnalysis スキーマ

```json
{
  "concepts": [
    {
      "id": "methodical_doubt",
      "name": "Methodical Doubt",
      "description": "Descartes' systematic approach to questioning all beliefs...",
      "original_quotes": [
        "I thought it necessary to reject as false everything...",
        "I resolved to assume that everything that ever entered into my mind..."
      ],
      "source_chunk": "PART IV"
    }
  ],
  "aporias": [
    {
      "id": "certainty_vs_action",
      "question": "How can one act decisively while systematically doubting everything?",
      "context": "Descartes faces the tension between...",
      "related_concepts": ["methodical_doubt", "provisional_morality"]
    }
  ],
  "relations": [
    {
      "source": "methodical_doubt",
      "target": "cogito",
      "relation_type": "depends_on",
      "evidence": "The Cogito emerges as the first certain truth after..."
    }
  ],
  "logic_flow": "Descartes begins by reflecting on his education and finding it lacking...",
  "arguments": [
    {
      "id": "cogito_argument",
      "premises": [
        "I can doubt the existence of the external world",
        "I can doubt the reliability of my senses",
        "But I cannot doubt that I am doubting"
      ],
      "conclusion": "Therefore, I exist as a thinking thing (cogito ergo sum)",
      "argument_type": "deductive",
      "source_chunk": "PART IV"
    }
  ],
  "rhetorical_strategies": [
    {
      "id": "wax_analogy",
      "strategy_type": "thought_experiment",
      "description": "Descartes uses the wax argument to demonstrate...",
      "original_quote": "Let us take, for example, this piece of wax...",
      "source_chunk": "PART IV"
    }
  ]
}
```

### フィールド詳細

| フィールド | 型 | 期待値 |
|-----------|------|--------|
| `concepts` | `list[Concept]` | 5〜10 個/チャンク |
| `aporias` | `list[Aporia]` | 2〜4 個/チャンク |
| `relations` | `list[ConceptRelation]` | 可変（概念間の依存関係） |
| `logic_flow` | `str` | 4〜5 文以上の詳細な推論の流れ |
| `arguments` | `list[ArgumentStructure]` | 1〜4 個/チャンク |
| `rhetorical_strategies` | `list[RhetoricalStrategy]` | 1〜3 個/チャンク |

### Concept の必須フィールド

| フィールド | 型 | 説明 |
|-----------|------|------|
| `id` | `str` | snake_case のスラッグ（例: `"methodical_doubt"`） |
| `name` | `str` | 表示名（例: `"Methodical Doubt"`） |
| `description` | `str` | 2〜3 文以上の詳細な説明 |
| `original_quotes` | `list[str]` | テキストからの直接引用（2〜4 件） |
| `source_chunk` | `str` | チャンクの part_id |

### relation_type の許容値

- `"depends_on"` — 概念 A は概念 B に依存する
- `"contradicts"` — 概念 A と概念 B は矛盾する
- `"evolves_into"` — 概念 A は概念 B へ発展する

### argument_type の許容値

- `"deductive"` — 演繹的
- `"inductive"` — 帰納的
- `"analogical"` — 類推的

### strategy_type の許容値

- `"metaphor"` — 隠喩
- `"analogy"` — 類推
- `"thought_experiment"` — 思考実験
- `"appeal_to_authority"` — 権威への訴え

### よくある問題

- **`concepts` が空**: LLM が JSON を返さなかった → ログの `llm_raw_response` を確認
- **`id` が重複**: 異なるチャンク間で同じ ID が使われる → synthesize ステージで統合される
- **`original_quotes` が空**: モデルがテキストからの引用抽出に失敗 → テキストが `[:20000]` で切り詰められていないか確認

---

## Stage 3: concept_graph

**ソース**: `src/reader/synthesizer.py` → `synthesize()`
**state キー**: `concept_graph`
**ファイル**: `03_concept_graph.json`
**Pydantic モデル**: `ConceptGraph`（`src/models.py`）

### スキーマ

```json
{
  "concepts": [
    {
      "id": "methodical_doubt",
      "name": "Methodical Doubt",
      "description": "...",
      "original_quotes": ["...", "..."],
      "source_chunk": "COMBINED"
    }
  ],
  "relations": [
    {
      "source": "methodical_doubt",
      "target": "cogito",
      "relation_type": "depends_on",
      "evidence": "..."
    }
  ],
  "aporias": [
    {
      "id": "certainty_vs_action",
      "question": "...",
      "context": "...",
      "related_concepts": ["methodical_doubt", "provisional_morality"]
    }
  ],
  "logic_flow": "全6部にわたる推論の連鎖を6〜8文で記述...",
  "core_frustration": "The fundamental unresolved tension that haunts the entire work..."
}
```

### バリデーション基準

| チェック項目 | 期待値 |
|-------------|--------|
| `concepts` の数 | 10〜20 個 |
| `relations` の数 | 8〜12 件 |
| `aporias` の数 | 4〜8 件 |
| `logic_flow` の長さ | 6〜8 文以上 |
| `core_frustration` | 非空の文字列 |
| 統合された概念の `source_chunk` | `"COMBINED"` |

### よくある問題

- **概念数が少ない（< 5）**: LLM が過度に統合している → `SYNTHESIS_PROMPT` で「10〜20 concepts」の指示を強調
- **`core_frustration` が空**: JSON パースに失敗しフォールバック値が使われた → ログ確認
- **`relations` の `source`/`target` が存在しない概念 ID を参照**: LLM がチャンク分析の ID と異なる ID を生成 → 下流での影響は限定的

---

## Stage 3b: research_context

**ソース**: `src/researcher/researcher.py` → `research()`
**state キー**: `research_context`
**ファイル**: `03b_research_context.json`

### スキーマ

```json
{
  "author_biography": "René Descartes (1596-1650) was born in La Haye en Touraine...",
  "historical_context": "The early 17th century was marked by...",
  "publication_history": "The Discourse was first published in Leiden in 1637...",
  "critical_reception": "The work was immediately controversial...",
  "modern_significance": "In the age of AI and machine learning...",
  "web_sources": [
    {
      "title": "Descartes - Stanford Encyclopedia of Philosophy",
      "url": "https://plato.stanford.edu/entries/descartes/"
    }
  ],
  "reference_files": [
    "gemini-houhoujosetsu.md"
  ]
}
```

### フィールド詳細

| フィールド | 型 | 説明 | 空の場合 |
|-----------|------|------|---------|
| `author_biography` | `str` | 著者の伝記的事実 | LLM 統合失敗 |
| `historical_context` | `str` | 時代背景 | 同上 |
| `publication_history` | `str` | 出版経緯 | 同上 |
| `critical_reception` | `str` | 批判的受容の歴史 | 同上 |
| `modern_significance` | `str` | 現代的意義 | 同上 |
| `web_sources` | `list[dict]` | 検索結果の出典 | 検索エンジン不可 |
| `reference_files` | `list[str]` | 使用した参考文献ファイル名 | 参考文献なし |

---

## Stage 3c: critique_report

**ソース**: `src/critic/critic.py` → `critique()`
**state キー**: `critique_report`
**ファイル**: `03c_critique_report.json`

### スキーマ

```json
{
  "critiques": [
    {
      "concept_id": "methodical_doubt",
      "concept_name": "Methodical Doubt",
      "historical_criticisms": [
        {
          "critic": "Pascal",
          "criticism": "Descartes tried to eliminate God from philosophy...",
          "era": "17th century"
        },
        {
          "critic": "Hume",
          "criticism": "Challenged the rationalist foundations...",
          "era": "18th century"
        }
      ],
      "counter_arguments": [
        "Descartes himself offered a proof of God's existence...",
        "The method was designed to achieve certainty, not nihilism..."
      ],
      "modern_reinterpretations": [
        "In cognitive science, systematic doubt is seen as...",
        "The Cartesian method parallels modern scientific skepticism..."
      ],
      "unresolved_controversies": [
        "Whether the Cogito is truly immune to doubt...",
        "The circularity problem (Cartesian Circle)..."
      ]
    }
  ],
  "overarching_debates": [
    {
      "debate": "Rationalism vs Empiricism",
      "positions": [
        "Descartes: innate ideas and rational certainty",
        "Locke/Hume: all knowledge derives from experience"
      ],
      "significance": "This debate shaped the entire Enlightenment..."
    }
  ],
  "reception_narrative": "When first published in 1637, the Discourse was..."
}
```

### バリデーション基準

| チェック項目 | 期待値 |
|-------------|--------|
| `critiques` の数 | 概念グラフの主要概念数に近い |
| 各 critique の `historical_criticisms` | 1 件以上 |
| `overarching_debates` | 1 件以上 |
| `reception_narrative` | 3〜5 文 |

---

## Stage 3d: enrichment

**ソース**: `src/director/enricher.py` → `enrich()`
**state キー**: `enrichment`
**ファイル**: `03d_enriched_context.json`

### スキーマ

```json
{
  "enrichment_summary": "René Descartes (1596-1650), a French philosopher...(800-1200 words in English)",
  "enrichment_summary_ja": "ルネ・デカルト（1596-1650）はフランスの哲学者であり...(1500-2500字の日本語)",
  "critique_perspectives_ja": "パスカルの批判：デカルトは神を最初の原因に還元しようとした...(400-800字の日本語)"
}
```

### バリデーション基準

| フィールド | 期待文字数 | 品質チェック |
|-----------|-----------|------------|
| `enrichment_summary` | 800〜1200 語（EN） | 固有名詞・年代を含む |
| `enrichment_summary_ja` | 1500〜2500 字（JA） | **これが最もよく不足する** |
| `critique_perspectives_ja` | 400〜800 字（JA） | 3〜4 つの批判的視点 |

### よくある問題

- **`enrichment_summary_ja` が短い（< 1000 字）**: `format="json"` が出力長を制限している → `num_predict=8192` が設定されていることを確認（enricher.py:67）
- **日本語の品質が低い**: 小さなモデル（llama3）では日本語の品質が不安定 → `command-r` を推奨

---

## Stage 3e: reading_material

**ソース**: `src/researcher/reading_material.py` → `generate_reading_material()`
**state キー**: `reading_material`
**ファイル**: `03e_reading_material.md`

### 型

```
str  # Markdown 形式の文字列
```

### 構成

```markdown
# {author_ja}『{book_title_ja}』に関する包括的構造分析および哲学的意義の再評価

## アブストラクト
(400-600 語の日本語テキスト)

## 第1章：第I部の詳細分析 —— PART I
### 概要
(...)
### 主要概念
(...)
### 論証構造の分析
(...)
### 修辞的技法
(...)
### 批判的考察
(...)

## 第2章：第II部の詳細分析 —— PART II
(同様の構成)

...

## 総合的結論および後世への影響
(600-1000 語の日本語テキスト)

## 参考文献
- [Source Title](url)
- reference_file.md
```

### バリデーション基準

| チェック項目 | 期待値 |
|-------------|--------|
| 全体の文字数 | 10,000〜15,000 字（JA） |
| 章数 | チャンク数 + 2（アブストラクト + 結論） |
| 各章の「批判的考察」セクション | 具体的な批評家名を含む |

---

## Stage 4: syllabus

**ソース**: `src/director/planner.py` → `plan()`
**state キー**: `syllabus`
**ファイル**: `04_syllabus.json`
**Pydantic モデル**: `Syllabus`（`src/models.py`）

### スキーマ

```json
{
  "mode": "curriculum",
  "episodes": [
    {
      "episode_number": 1,
      "title": "The Crisis of Knowledge",
      "theme": "Why does Descartes reject everything he was taught?",
      "concept_ids": ["educational_disillusionment", "methodical_doubt"],
      "aporia_ids": ["certainty_vs_action"],
      "cliffhanger": "But if you doubt everything, how do you even get out of bed?",
      "cognitive_bridge": "Like clearing your browser history and starting fresh — Descartes wanted a factory reset for human knowledge"
    }
  ],
  "meta_narrative": "A young philosopher discovers that everything he knows is wrong..."
}
```

### Episode の必須フィールド

| フィールド | 型 | 説明 |
|-----------|------|------|
| `episode_number` | `int` | エピソード番号（1 始まり） |
| `title` | `str` | 英語タイトル |
| `theme` | `str` | 中心的な問い/テーマ（英語） |
| `concept_ids` | `list[str]` | 概念グラフの concept ID を参照（2〜4 件） |
| `aporia_ids` | `list[str]` | 概念グラフの aporia ID を参照（1〜2 件） |
| `cliffhanger` | `str` | 次回への引き（英語） |
| `cognitive_bridge` | `str` | 現代との接点（英語） |

### モード別のエピソード数

| モード | エピソード数 |
|--------|-------------|
| `essence` | 1 |
| `curriculum` | 6 |
| `topic` | 1〜2 |

### よくある問題

- **`episodes` が空リスト**: JSON パース失敗 → ログ確認
- **`episodes` に非 dict 要素が含まれる**: LLM がリスト内に文字列を混入 → `planner.py:236-239` の `isinstance` フィルタで除去される
- **`concept_ids` が概念グラフに存在しない ID を参照**: LLM が独自の ID を生成 → scriptwriter が概念情報を見つけられない（品質低下だが致命的ではない）

---

## Stage 5: scripts

**ソース**: `src/dramaturg/scriptwriter.py` → `write_scripts()`
**state キー**: `scripts`
**ファイル**: `05_scripts.json`
**Pydantic モデル**: `Script`（`src/models.py`）

### スキーマ

```json
[
  {
    "episode_number": 1,
    "title": "知の危機 — なぜデカルトは全てを疑ったのか",
    "opening_bridge": "AIが人間の仕事を奪うかもしれない時代。でも、そもそも「知る」とは何でしょうか？",
    "dialogue": [
      {
        "speaker": "Host",
        "line": "みなさん、こんにちは。今日は17世紀の哲学者デカルトの『方法序説』を読み解いていきます。"
      },
      {
        "speaker": "Descartes",
        "line": "ようこそ。私の著作を現代の視点から議論できるとは光栄です。"
      }
    ],
    "closing_hook": "デカルトは全てを疑いました。次回は、彼がその懐疑の果てに見つけた「たった一つの確実なもの」を探ります。"
  }
]
```

### バリデーション基準

| チェック項目 | 期待値 |
|-------------|--------|
| スクリプト数 | `syllabus.episodes` の数と一致 |
| `dialogue` の発言数 | 50〜65 行/エピソード |
| 各 `line` の言語 | **全て日本語**（英語が混入しないこと） |
| `speaker` の値 | ペルソナ設定の `persona_a.name` または `persona_b.name` |
| `title` | 日本語 |

### DialogueLine の構造

| フィールド | 型 | 説明 |
|-----------|------|------|
| `speaker` | `str` | 話者名（ペルソナ名と一致すること） |
| `line` | `str` | 台詞（1〜4 文。日本語） |

### よくある問題

- **英語が混入**: Dramaturg モデルがプロンプトの日本語指示を無視 → `qwen3-next` を推奨
- **`dialogue` が空**: JSON パース失敗 → `llm_raw_response` を確認（`format="json"` が scriptwriter では**未使用**のため、JSON 以外のテキストが含まれる場合がある）
- **発言数が少ない（< 30）**: モデルが短い台本を生成 → temperature を上げるか、プロンプトの品質基準を強調

---

## Stage 6: audio_metadata

**ソース**: `src/audio/synthesizer.py` → `synthesize_audio()`
**state キー**: `audio_metadata`
**ファイル**: `06_audio.json`
**Pydantic モデル**: `AudioEpisodeMetadata`（`src/models.py`）

### スキーマ

```json
[
  {
    "episode_number": 1,
    "title": "知の危機 — なぜデカルトは全てを疑ったのか",
    "file": "/Users/.../data/run_20260212_100013/06_audio/ep01.mp3",
    "duration_sec": 612.5,
    "file_size_bytes": 14700000,
    "lines_synthesized": 58,
    "errors": 2,
    "synthesis_time_sec": 245.3
  }
]
```

### フィールド詳細

| フィールド | 型 | 説明 |
|-----------|------|------|
| `episode_number` | `int` | エピソード番号 |
| `title` | `str` | エピソードタイトル |
| `file` | `str \| null` | MP3 ファイルの絶対パス。音声生成失敗時は `null` |
| `duration_sec` | `float` | 音声の長さ（秒） |
| `file_size_bytes` | `int` | ファイルサイズ（バイト） |
| `lines_synthesized` | `int` | 合成に成功した行数 |
| `errors` | `int` | 合成に失敗した行数 |
| `synthesis_time_sec` | `float` | 合成にかかった時間（秒） |

### バリデーション基準

| チェック項目 | 期待値 |
|-------------|--------|
| `duration_sec` | 1 エピソード 5〜15 分（300〜900 秒） |
| `errors` | 0 が理想。5 以上は要調査 |
| `file` | `null` でないこと（VOICEVOX 接続確認） |
| エピソード数 | スクリプト数と一致 |

---

## thinking_log

**ソース**: `src/logger.py`
**state キー**: `thinking_log`
**ファイル**: `logs/run_YYYYMMDD_HHMMSS.json`

### ThinkingStep の構造

```json
{
  "timestamp": "2026-02-12T10:01:23.456789",
  "layer": "reader",
  "node": "analyst",
  "action": "analyze_chunk:PART I",
  "input_summary": "Chunk 'PART I': 15234 chars",
  "llm_prompt": "You are a philosopher performing deep hermeneutic analysis...(プロンプト全文)",
  "llm_raw_response": "{\"concepts\": [...], \"aporias\": [...]}...(LLM の生の回答)",
  "parsed_output": {
    "concepts": [...],
    "aporias": [...]
  },
  "error": null,
  "reasoning": "Extracted 8 concepts, 3 aporias, 5 relations from PART I"
}
```

### ThinkingLog のルート構造

```json
{
  "run_id": "run_20260212_100013",
  "started_at": "2026-02-12T10:00:13.456789",
  "book_title": "Discourse on the Method",
  "mode": "essence",
  "steps": [ ... ],
  "final_concept_graph": { ... },
  "final_syllabus": { ... }
}
```

### layer の許容値

| 値 | 対応ステージ |
|-----|------------|
| `"reader"` | ingest, analyze_chunks, synthesize |
| `"researcher"` | research (web_search, reference_loader, integration), critique, reading_material |
| `"director"` | enrich, plan |
| `"dramaturg"` | write_scripts |
| `"audio"` | synthesize_audio |
| `"translator"` | translate |

### error フィールドの読み方

| 値 | 意味 |
|-----|------|
| `null` | 正常完了 |
| `"JSON parse error: ..."` | LLM の出力が有効な JSON ではなかった |
| `"Validation error: ..."` | JSON は有効だが Pydantic バリデーションに失敗 |

---

## Pydantic モデル一覧

`src/models.py` で定義。`concept_graph` と `syllabus` と `scripts` の各要素は Pydantic でバリデーションされる。

```
ConceptGraph
  ├── concepts: list[Concept]
  │     ├── id: str
  │     ├── name: str
  │     ├── description: str
  │     ├── original_quotes: list[str]
  │     └── source_chunk: str
  ├── relations: list[ConceptRelation]
  │     ├── source: str
  │     ├── target: str
  │     ├── relation_type: str
  │     └── evidence: str
  ├── aporias: list[Aporia]
  │     ├── id: str
  │     ├── question: str
  │     ├── context: str
  │     └── related_concepts: list[str]
  ├── logic_flow: str
  └── core_frustration: str

Syllabus
  ├── mode: str
  ├── episodes: list[Episode]
  │     ├── episode_number: int
  │     ├── title: str
  │     ├── theme: str
  │     ├── concept_ids: list[str]
  │     ├── aporia_ids: list[str]
  │     ├── cliffhanger: str
  │     └── cognitive_bridge: str
  └── meta_narrative: str

Script
  ├── episode_number: int
  ├── title: str
  ├── opening_bridge: str
  ├── dialogue: list[DialogueLine]
  │     ├── speaker: str
  │     └── line: str
  └── closing_hook: str

AudioEpisodeMetadata
  ├── episode_number: int
  ├── title: str
  ├── file: str | None
  ├── duration_sec: float
  ├── file_size_bytes: int
  ├── lines_synthesized: int
  ├── errors: int
  └── synthesis_time_sec: float
```
