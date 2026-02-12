# プロンプトテンプレート・リファレンス

各 LLM コールで使用されるプロンプトテンプレートの完全なリファレンス。
プロンプトチューニングやデバッグの際に、実際に LLM に送信されるテキストの構造を把握するために使用する。

---

## 目次

1. [全体構造](#全体構造)
2. [ANALYSIS_PROMPT — チャンク分析](#analysis_prompt)
3. [SYNTHESIS_PROMPT — 概念グラフ合成](#synthesis_prompt)
4. [SUMMARIZE_PROMPT — 参考文献要約](#summarize_prompt)
5. [INTEGRATION_PROMPT — 研究文脈統合](#integration_prompt)
6. [CRITIQUE_PROMPT — 歴史的批判生成](#critique_prompt)
7. [ENRICHMENT_PROMPT — EN/JA 統合要約](#enrichment_prompt)
8. [Reading Material プロンプト群](#reading-material-prompts)
9. [ESSENCE/CURRICULUM/TOPIC_PROMPT — エピソード設計](#plan-prompts)
10. [SCRIPT_PROMPT — 対話台本生成](#script_prompt)
11. [TRANSLATE_PROMPT — 日本語翻訳](#translate_prompt)
12. [共通パターンと注意点](#共通パターン)

---

## 全体構造

### LLM コール共通仕様

| 項目 | Reader 層 | Dramaturg 層 | Translator 層 |
|------|----------|-------------|-------------|
| ライブラリ | `langchain_ollama.ChatOllama` | 同左 | 同左 |
| 呼び出し方法 | `llm.invoke(prompt).content` | 同左 | 同左 |
| Temperature | 0.1〜0.3（低: 構造化出力向け） | 0.7（高: 創造的生成） | 0.1（低: 正確な翻訳） |
| `format="json"` | **有効**（JSON 出力を強制） | **無効**（自由テキスト） | **無効** |
| `num_ctx` | 16384〜32768 | 32768 | 8192 |
| `num_predict` | デフォルト（enricher のみ 8192） | デフォルト | デフォルト |

### 変数展開の流れ

```
テンプレート文字列（ソースコード内）
    ↓ Python str.format() で変数を展開
展開済みプロンプト
    ↓ ChatOllama.invoke() に送信
LLM の生テキスト回答
    ↓ extract_json() で JSON を抽出
構造化データ (dict)
```

**注意**: テンプレート内の `{{` と `}}` は Python の `str.format()` エスケープ。実際の LLM への入力では `{` と `}` として表示される。

---

## ANALYSIS_PROMPT

**ファイル**: `src/reader/analyst.py:30-93`
**ノード**: `analyze_chunks`
**モデル**: Reader（デフォルト: llama3）
**設定**: `temperature=0.1, num_ctx=16384, format="json"`
**呼び出し回数**: N 回（チャンク数）

### テンプレート変数

| 変数 | ソース | 例 |
|------|--------|-----|
| `{part_id}` | チャンクの先頭行 | `"PART IV"` |
| `{text}` | チャンクテキスト `[:20000]` | (最大 20,000 文字) |
| `{key_terms_instruction}` | `book_config.context.key_terms` から生成 | `"Look especially for these known terms/techniques: Cogito ergo sum, Methodical Doubt"` |

### プロンプトの構造

```
[役割] 哲学的テキストの解釈学的分析者
[指示] 7次元の構造化抽出:
  1. Concepts (5-10個): id, name, description(2-3文), original_quotes(2-4件), source_chunk
  2. Aporias (2-4個): id, question, context(2-3文), related_concepts
  3. Relations: source, target, relation_type, evidence
  4. Logic flow: 4-5文以上の推論の流れ
  5. Arguments (1-4個): id, premises[], conclusion, argument_type, source_chunk
  6. Named Philosophical Moves + key_terms_instruction
  7. Rhetorical Strategies (1-3個): id, strategy_type, description, original_quote
[出力形式] JSON（厳密な構造指定あり）
[入力] TEXT CHUNK ({part_id}): {text}
```

### 期待される出力

```json
{
  "concepts": [...],
  "aporias": [...],
  "relations": [...],
  "logic_flow": "...",
  "arguments": [...],
  "rhetorical_strategies": [...]
}
```

### よくある失敗パターン

| 症状 | 原因 | 対策 |
|------|------|------|
| JSON パースエラー | llama3 が JSON の前にテキストを出力 | `extract_json()` で自動処理される。頻発する場合は `format="json"` の確認 |
| concepts が 0〜2 個しか出ない | テキストが短い or モデルが浅い分析 | `command-r` に変更、テキスト長の確認 |
| original_quotes が空 | モデルがテキストから引用を抽出できない | `{text}` が `[:20000]` で切り詰められすぎていないか確認 |
| rhetorical_strategies がない | llama3 は項目 5-7 を生成しないことがある | 許容範囲（フォールバックで空リスト）。品質向上には大型モデル推奨 |

### リトライロジック

`_invoke_with_retry()` （`analyst.py:15-27`）:
- 最大 3 回リトライ
- 失敗時の待機: 10s, 20s, 30s（指数バックオフ）
- 3 回目も失敗したら例外を raise

---

## SYNTHESIS_PROMPT

**ファイル**: `src/reader/synthesizer.py:11-61`
**ノード**: `synthesize`
**モデル**: Reader
**設定**: `temperature=0.1, num_ctx=32768, format="json"`
**呼び出し回数**: 1 回

### テンプレート変数

| 変数 | ソース | 例 |
|------|--------|-----|
| `{chunk_count}` | `len(chunk_analyses)` | `6` |
| `{analyses_json}` | 全チャンク分析の JSON（`[:25000]` で切り詰め） | (大きな JSON) |
| `{work_description}` | `book_config.prompt_fragments.work_description` | `"Descartes' \"Discourse on the Method\" (1637)..."` |

### プロンプトの構造

```
[役割] 分析結果を統合するシステマタイザー
[指示] 5つのタスク:
  1. 概念の重複排除（目標 10-20 概念）— 同一概念のみ統合、関連概念は別々に保持
  2. クロスチャンク関係構築（目標 8-12 関係）— 全体の推論チェーンをマッピング
  3. Core frustration の特定 — 著作全体を貫く未解決の知的緊張
  4. アポリアの保全（目標 4-8）
  5. 統合 logic_flow（6-8 文以上）
[入力] CHUNK ANALYSES: {analyses_json}
[出力形式] ConceptGraph JSON
```

### 注意点

- `analyses_json` が 25,000 文字を超える場合は切り詰められる → 後半チャンクの情報が失われる可能性
- `ConceptGraph(**parsed)` で Pydantic バリデーションされる → フィールド不足はエラーとしてログに記録

---

## SUMMARIZE_PROMPT

**ファイル**: `src/researcher/reference_loader.py:10-37`
**ノード**: `research`（参考文献要約フェーズ）
**モデル**: Reader
**設定**: `temperature=0.1, num_ctx=32768, format="json"`
**呼び出し回数**: 参考文献ファイル数

### テンプレート変数

| 変数 | ソース |
|------|--------|
| `{book_title}` | `book_config.book.title` |
| `{author}` | `book_config.book.author` |
| `{text}` | 参考文献のテキスト `[:30000]` |

### 期待される出力

```json
{
  "author_biography": "...",
  "historical_context": "...",
  "publication_history": "...",
  "key_arguments": "...",
  "critical_reception": "...",
  "modern_significance": "..."
}
```

---

## INTEGRATION_PROMPT

**ファイル**: `src/researcher/researcher.py:12-42`
**ノード**: `research`（統合フェーズ）
**モデル**: Reader
**設定**: `temperature=0.1, num_ctx=32768, format="json"`
**呼び出し回数**: 1 回

### テンプレート変数

| 変数 | ソース | 切り詰め |
|------|--------|---------|
| `{book_title}` | `book_config.book.title` | — |
| `{author}` | `book_config.book.author` | — |
| `{year}` | `book_config.book.year` | — |
| `{web_results_text}` | `format_search_results()` の出力 | 10,000 文字 |
| `{reference_summaries_text}` | 参考文献要約の JSON | 10,000 文字 |

### プロンプトの構造

```
[役割] リサーチアシスタント
[指示] Web 検索結果 + 参考文献要約を5カテゴリに整理:
  1. author_biography
  2. historical_context
  3. publication_history
  4. critical_reception
  5. modern_significance
[入力] WEB SEARCH RESULTS: ... + REFERENCE FILE SUMMARIES: ...
[出力形式] JSON
```

### よくある失敗パターン

- **Web 検索結果が空**: `TAVILY_API_KEY` 未設定かつ DuckDuckGo も利用不可 → `"(No web search results available)"` が入力される
- **参考文献がない**: `"(No reference files available)"` が入力される → 統合の品質は低下するが致命的ではない

---

## CRITIQUE_PROMPT

**ファイル**: `src/critic/critic.py:10-54`
**ノード**: `critique`
**モデル**: Reader
**設定**: `temperature=0.2, num_ctx=32768, format="json"`
**呼び出し回数**: 1 回

### テンプレート変数

| 変数 | ソース | 切り詰め |
|------|--------|---------|
| `{book_title}` | `book_config.book.title` | — |
| `{author}` | `book_config.book.author` | — |
| `{concept_graph_json}` | 概念グラフの JSON | 12,000 文字 |
| `{research_context}` | 研究文脈の JSON | 8,000 文字 |
| `{notable_critics_text}` | `book_config.context.notable_critics` | — |

### notable_critics_text の展開例

```
- **Pascal**: Criticized for reducing God to a first cause
- **Hume**: Challenged rationalist foundations
- **Kant**: Synthesized rationalism and empiricism
- **Arnauld**: Pointed out the Cartesian Circle
- **Gassendi**: Criticized Cogito and dualism from empiricist standpoint
```

### 期待される出力

```json
{
  "critiques": [{ "concept_id", "concept_name", "historical_criticisms", "counter_arguments", "modern_reinterpretations", "unresolved_controversies" }],
  "overarching_debates": [{ "debate", "positions", "significance" }],
  "reception_narrative": "..."
}
```

---

## ENRICHMENT_PROMPT

**ファイル**: `src/director/enricher.py:10-50`
**ノード**: `enrich`
**モデル**: Reader
**設定**: `temperature=0.2, num_ctx=32768, num_predict=8192, format="json"`
**呼び出し回数**: 1 回

### テンプレート変数

| 変数 | ソース | 切り詰め |
|------|--------|---------|
| `{research_context_json}` | 研究文脈全体の JSON | 10,000 文字 |
| `{critique_report_json}` | 批評レポート全体の JSON | 10,000 文字 |

### 出力の 3 つのフィールド

| フィールド | 言語 | 目標文字数 | 用途 |
|-----------|------|-----------|------|
| `enrichment_summary` | 英語 | 800〜1200 語 | `plan` のプロンプトに注入 |
| `enrichment_summary_ja` | 日本語 | 1500〜2500 字 | `write_scripts` と `reading_material` に注入 |
| `critique_perspectives_ja` | 日本語 | 400〜800 字 | `write_scripts` に注入 |

### 既知の問題

**`num_predict=8192` が重要**: enricher は3つの長いテキストフィールドを同時に生成する必要があるため、デフォルトの `num_predict`（通常 2048〜4096）では出力が途中で切れる。`num_predict=8192` が設定されていない場合、`enrichment_summary_ja` が特に短くなる。

**`format="json"` の制約**: JSON モードでは LLM がトークン予算を保守的に使う傾向があり、日本語テキストの生成量が制限される。これは既知の制約で、完全な解決は困難。

---

## Reading Material プロンプト群

**ファイル**: `src/researcher/reading_material.py`
**ノード**: `generate_reading_material`
**モデル**: Reader
**設定**: `temperature=0.3, num_ctx=32768`（**`format="json"` なし** — 自由テキスト出力）

### ABSTRACT_PROMPT（55-76行目）

```
[役割] 学術ライター
[指示] 400-600 語の日本語アブストラクト:
  1. 何について・なぜ書かれたか（歴史的文脈込み）
  2. 主要な哲学的主張と貢献
  3. 歴史的意義
  4. 現代的relevance
[入力] SOURCE MATERIAL: {enrichment_summary} (JA 優先、なければ EN)
[出力] プレーンテキスト（JSON ラッピングなし、マークダウン見出しなし）
```

**変数**: `{book_title}`, `{author}`, `{year}`, `{enrichment_summary}`

### CHAPTER_ANALYSIS_PROMPT（78-120行目）

```
[役割] 学術ライター
[指示] 600-1000 語の日本語分析エッセイ（## サブセクション構造）:
  ## 概要, ## 主要概念, ## 論証構造の分析, ## 修辞的技法, ## 批判的考察
[入力]
  - SECTION: {section_label}
  - CHUNK TEXT (first 2000 chars): {chunk_preview}
  - ANALYSIS DATA: Concepts, Arguments, Rhetorical Strategies, Logic Flow
  - {critique_context}: 批評レポートから該当概念の批判を抽出
  - {part_critics_instruction}: PART_CRITICS マッピングから Part 別の批評家指示
[出力] プレーンテキスト（## サブセクション付き）
```

**PART_CRITICS マッピング** (`reading_material.py:25-49`): Part 1〜6 に対する批評家の固定マッピング。例:
- Part 4: アルノー（デカルトの循環）、ガッサンディ（経験主義的批判）
- Part 5: ハーヴェイ（血液循環の論争）、ラ・メトリ（人間機械論）

### CONCLUSION_PROMPT（122-157行目）

```
[役割] 学術ライター
[指示] 600-1000 語の日本語結論:
  1. {author}の革命（主観性の確立）
  2. 批判的受容（パスカル、心身問題、{critics_list}）
  3. 現代的意義（AI、環境倫理、批判的思考）
  4. 結語
[入力] ENRICHMENT CONTEXT, CRITIQUE PERSPECTIVES, OVERARCHING DEBATES
```

### 呼び出し回数

```
合計 = 1 (abstract) + N (章数 = チャンク数) + 1 (conclusion) = N + 2
```

---

## Plan プロンプト群 {#plan-prompts}

**ファイル**: `src/director/planner.py`
**ノード**: `plan`
**モデル**: Reader
**設定**: `temperature=0.3, num_ctx=16384, format="json"`
**呼び出し回数**: 1 回

### 共通テンプレート変数

| 変数 | ソース |
|------|--------|
| `{concept_graph_json}` | 概念グラフの JSON（`[:15000]` で切り詰め） |
| `{work_description}` | `book_config.prompt_fragments.work_description` |
| `{topic}` | CLI `--topic` 引数（topic モードのみ） |
| `{key_terms_guidance}` | `book_config.context.key_terms` から生成 |

### ESSENCE_PROMPT（11-50行目）

```
[役割] ポッドキャストディレクター
[指示] 単一のエピソードを設計:
  - 最も重要なアポリア 1 つ + コア概念 2-3 個を選択
  - 「著作の鼓動」を捉える
[出力] { mode: "essence", episodes: [1つ], meta_narrative }
```

### CURRICULUM_PROMPT（52-108行目）

```
[役割] ポッドキャストディレクター
[指示] 正確に 6 エピソードを設計:
  Ep1: 知の危機（Part I）
  Ep2: 方法の発見（Part II）
  Ep3: 懐疑しながら生きる（Part III）
  Ep4: 突破口（Part IV）
  Ep5: 機械の宇宙（Part V）
  Ep6: 科学と社会（Part VI）
[出力] { mode: "curriculum", episodes: [6つ], meta_narrative }
```

### TOPIC_PROMPT（110-151行目）

```
[役割] ポッドキャストディレクター
[指示] {topic} に焦点を当てた 1-2 エピソードを設計
[出力] { mode: "topic", episodes: [1-2], meta_narrative }
```

### enrichment の注入

3つのプロンプト全てに対し、`enrichment.enrichment_summary` が存在する場合、プロンプト末尾に追加される:

```
## Background Research Context
{enrichment_summary}

Use this background to design episodes that incorporate historical context
and critical perspectives. Each episode should include at least one reference
to the work's historical reception or a notable criticism.
```

---

## SCRIPT_PROMPT

**ファイル**: `src/dramaturg/scriptwriter.py:11-95`
**ノード**: `write_scripts`
**モデル**: Dramaturg（デフォルト: qwen3-next）
**設定**: `temperature=0.7, num_ctx=32768`（**`format="json"` なし**）
**呼び出し回数**: M 回（エピソード数）

### テンプレート変数

| 変数 | ソース |
|------|--------|
| `{author_ja}` | `book_config.book.author_ja` |
| `{book_title_ja}` | `book_config.book.title_ja` |
| `{book_title}` | `book_config.book.title` |
| `{total_episodes}` | `len(syllabus.episodes)` |
| `{episode_number}` | 現在のエピソード番号 |
| `{episode_context}` | エピソード位置に応じた文脈（初回/中間/最終回で異なる） |
| `{persona_a_name}`, `{persona_a_role}`, `{persona_a_description}`, `{persona_a_tone}`, `{persona_a_speaking_style}` | ペルソナ A の設定 |
| `{persona_b_name}`, `{persona_b_role}`, `{persona_b_description}`, `{persona_b_tone}`, `{persona_b_speaking_style}` | ペルソナ B の設定 |
| `{theme}` | エピソードのテーマ |
| `{cognitive_bridge}` | 現代との接点 |
| `{concepts_text}` | `_format_concepts()` で整形 — 主要概念と補助概念を区別 |
| `{aporias_text}` | `_format_aporias()` で整形 — 主要アポリアと補助アポリアを区別 |
| `{enrichment_block}` | `enrichment_summary_ja` + `critique_perspectives_ja`（あれば） |
| `{act1_instruction}` | エピソード位置に応じた第1幕の指示 |
| `{act2_extra}` | enrichment がある場合: `"少なくとも1つの歴史的批判に言及すること"` |
| `{act3_extra}` | enrichment がある場合: `"現代における再解釈や影響に言及すること"` |

### プロンプトの構造（日本語）

```
あなたは一流のポッドキャスト台本作家です。

## シリーズ情報
  - 著者、書籍、シリーズ構成
  - エピソード位置の文脈

## 登場人物
  - persona_a と persona_b の詳細設定

## エピソード情報
  - テーマ、認知的ブリッジ

## 扱う概念
  - 主要概念（原著の引用付き）
  - 補助概念

## 扱うアポリア
  - 主要アポリア
  - 補助アポリア

## 研究背景（enrichment）
  - enrichment_summary_ja
  - critique_perspectives_ja

## 台本の構成（3幕構成）
  第1幕: 導入と問題提起（3分 / 15-20発言）
  第2幕: 哲学的掘り下げ（5分 / 20-30発言）
  第3幕: 統合と余韻（2分 / 10-15発言）

## 品質基準
  - 50-65発言
  - 全て日本語
  - 原文の直接引用禁止
```

### episode_context の分岐

| エピソード位置 | episode_context の内容 | act1_instruction の内容 |
|--------------|---------------------|----------------------|
| 初回 | `"これはシリーズの第1回です..."` | `"【重要】第1回なので「前回」への言及は絶対にしないこと"` + 書籍紹介の指示 |
| 中間 | 前回・次回のテーマを記載 | `"opening_bridgeで前回の議論を簡潔に振り返り..."` |
| 最終回 | `"これはシリーズの最終回です..."` + 前回テーマ | `"シリーズ全体のまとめも意識する"` |

### concepts_text の構造（_format_concepts の出力）

```
### 主要概念（このエピソードの中心）
- **Methodical Doubt**（methodical_doubt）: Descartes' systematic approach...
  原著の該当箇所（参考情報。対話では自分の言葉で言い換えること）:
    「I thought it necessary to reject as false everything...」
    「I resolved to assume that everything...」

### 補助概念（背景知識として参照可能）
- **Provisional Morality**（provisional_morality）: ...
```

### よくある失敗パターン

| 症状 | 原因 | 対策 |
|------|------|------|
| 英語が混入する | モデルが日本語指示を無視 | `qwen3-next` を使用（日本語能力が高い） |
| dialogue が空 | JSON パース失敗（`format="json"` が未設定のため） | `extract_json()` のフォールバック確認。ログの `llm_raw_response` 参照 |
| 発言数が少ない（< 30） | モデルが品質基準を遵守しない | `temperature` を上げる、`num_ctx` を増やす |
| 「前回」への言及（初回で） | episode_context の生成ロジックのバグ or モデルの無視 | ログでプロンプトの act1_instruction を確認 |
| speaker 名がペルソナ名と不一致 | LLM が独自の名前を使用 | VOICEVOX では `_resolve_speaker_id` がフォールバックする |

---

## TRANSLATE_PROMPT

**ファイル**: `src/translator.py:9-20`
**ノード**: `translate`
**モデル**: Translator（デフォルト: translategemma:12b）
**設定**: `temperature=0.1, num_ctx=8192`（**`format="json"` なし**）
**呼び出し回数**: S 回（翻訳対象セクション数）

### テンプレート変数

| 変数 | ソース |
|------|--------|
| `{work_description}` | `state.work_description` |
| `{text}` | マークダウンセクション（最大 3,000 文字） |

### プロンプトの構造

```
You are a professional English (en) to Japanese (ja) translator.
[コンテキスト] {work_description}
[要求] 哲学用語の正確な翻訳、マークダウン書式の維持
[制約] 翻訳のみ出力（コメントなし）

{text}
```

### チャンク分割ロジック

`_split_by_sections()` (`translator.py:27-66`):

1. `##` と `###` 見出しで分割
2. 各セクションが `MAX_CHUNK_CHARS = 3000` 以下ならそのまま
3. 超過する場合は段落（`\n\n`）単位でさらに分割

### 翻訳対象ファイル

| ソース | 出力 |
|--------|------|
| `02_chunk_analyses.md` | `02_chunk_analyses_ja.md` |
| `03_concept_graph.md` | `03_concept_graph_ja.md` |
| `04_syllabus.md` | `04_syllabus_ja.md` |

---

## 共通パターン

### JSON 抽出（extract_json）

**ファイル**: `src/logger.py:68-95`

LLM の出力から JSON を抽出する共通ユーティリティ。以下の順序で試行:

1. `` ```json ... ``` `` コードフェンス
2. `` ``` ... ``` `` 汎用コードフェンス
3. 最初の `{` から最後の `}` まで（テキストプリアンブル付き JSON）

**失敗時**: `json.JSONDecodeError` を raise → 各ノードでキャッチされ、フォールバック値が使用される。

### 入力の切り詰め

各プロンプトは LLM のコンテキストウィンドウに収まるよう、入力データを切り詰める。

| ノード | 変数 | 上限 |
|--------|------|------|
| analyze_chunks | `{text}` | 20,000 文字 |
| synthesize | `{analyses_json}` | 25,000 文字 |
| research (integration) | `{web_results_text}` | 10,000 文字 |
| research (integration) | `{reference_summaries_text}` | 10,000 文字 |
| critique | `{concept_graph_json}` | 12,000 文字 |
| critique | `{research_context}` | 8,000 文字 |
| enrich | `{research_context_json}` | 10,000 文字 |
| enrich | `{critique_report_json}` | 10,000 文字 |
| plan | `{concept_graph_json}` | 15,000 文字 |
| reading_material | `{chunk_preview}` | 2,000 文字 |
| reference_loader | `{text}` | 30,000 文字 |
| translate | セクション | 3,000 文字 |

### エラーハンドリングの共通パターン

全 LLM ノードは以下の共通パターンに従う:

```python
raw_response = llm.invoke(prompt).content  # LLM 呼び出し

parsed = None
error = None
try:
    parsed = extract_json(raw_response)     # JSON 抽出
    PydanticModel(**parsed)                  # バリデーション（あれば）
except (json.JSONDecodeError, ...) as e:
    error = f"JSON parse error: {e}"
    parsed = { ... }                         # フォールバック値
except Exception as e:
    error = f"Validation error: {e}"

steps.append(create_step(                    # ログ記録
    llm_prompt=prompt,
    llm_raw_response=raw_response,
    parsed_output=parsed,
    error=error,
))
```

**重要**: エラーが発生してもパイプラインは停止しない。フォールバック値（空のリスト/文字列）で処理を継続する。エラーは `thinking_log` の `error` フィールドに記録される。
