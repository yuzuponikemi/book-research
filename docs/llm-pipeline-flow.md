# LLM パイプラインフロー

各サービスが LLM をどのように呼び出すかの詳細。プロンプトチューニングやデバッグの参考資料。

---

## モデル役割分担

| モデル種別 | CLI 引数 | デフォルト | 用途 |
|---|---|---|---|
| **Reader モデル** | `--reader-model` | `llama3` | 分析・統合・計画（構造化 JSON 出力、`format="json"` 必須） |
| **Dramaturg モデル** | `--dramaturg-model` | `qwen3-next` | 日本語対話台本生成（創造的テキスト出力） |
| **Translator モデル** | `--translator-model` | `translategemma:12b` | 英 → 日翻訳 |

```mermaid
graph LR
    A[原テキスト] -->|ingest| B[ChunksV1]
    B -->|analyze_chunks<br>Reader × N| C[chunk_analyses]
    C -->|synthesize_graph<br>Reader × 1| D[ConceptGraphV1]

    S[Subject/Author] -->|web_research<br>Reader × K+1| D

    D -->|produce: planner<br>Reader × 1| E[SyllabusV1]
    E -->|produce: podcast<br>Dramaturg × M| F[list[ScriptV1]]

    F -->|synthesize_audio<br>VOICEVOX| G[MP3]
    F -->|translate<br>Translator × S| H[*_ja.md]
```

---

## サービス別 LLM 呼び出し詳細

### `analyst/extractor.py` — チャンク別概念抽出

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 哲学的テキストの解釈学的分析者 |
| **呼び出し回数** | N 回（チャンク数） |
| **モデル設定** | Reader モデル、temperature=0.1、format="json" |
| **入力** | チャンクテキスト（〜20k 文字）、part_id、key_terms |
| **プロンプト** | 7次元の構造化抽出（概念・アポリア・関係・論理の流れ・論証構造・哲学的手法・修辞戦略） |
| **出力** | `{concepts, aporias, relations, arguments, rhetorical_strategies, logic_flow}` |
| **注意** | チャンクは逐次処理。並列実行禁止（Apple Silicon ハング） |

### `analyst/synthesizer.py` — 概念グラフ合成

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 分析結果を統合するシステマタイザー |
| **呼び出し回数** | 1 回 |
| **モデル設定** | Reader モデル、temperature=0.1、format="json" |
| **入力** | 全チャンク分析の圧縮サマリー、作品情報 |
| **プロンプト** | 重複排除（10〜20概念）、クロスチャンク関係構築（8〜12関係）、コアフラストレーション特定 |
| **出力** | `ConceptGraphV1` JSON |

### `web_researcher/planner.py` — 見出し決定

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 学術的アウトライン作成者 |
| **呼び出し回数** | 0〜1 回（book config に見出しがあれば 0 回） |
| **入力** | 著者・タイトル・説明文 |
| **出力** | `list[Heading]`（id + title + description） |

### `web_researcher/searcher.py` — クエリ生成・Web 検索

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 学術検索の専門家 |
| **呼び出し回数** | K 回（見出し数）＋ Web API 呼び出し |
| **入力** | 見出し（Heading）ごとに 3〜5 個のクエリを生成 |
| **検索エンジン** | Tavily（優先）/ DuckDuckGo（フォールバック） |
| **出力** | `dict[heading_id → list[SearchResult]]` |

### `web_researcher/aggregator.py` — 検索結果要約

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 研究リサーチャー |
| **呼び出し回数** | K 回（見出し数） |
| **入力** | 各見出しの検索結果スニペット群 |
| **出力** | `list[SynthesizedChunk]`（段落レベルの要約） |

### `producer/planner.py` — エピソード設計

| 項目 | 内容 |
|---|---|
| **LLM ロール** | ポッドキャストのショーランナー |
| **呼び出し回数** | 1 回 |
| **モデル設定** | Reader モデル、temperature=0.3、format="json" |
| **入力** | ConceptGraphV1、モード設定 |
| **プロンプト** | 概念・アポリアをエピソード別にキュレーション。Cognitive Bridge と Cliffhanger を設定 |
| **出力** | `SyllabusV1` JSON |

### `producer/podcast.py` — 対話台本生成

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 一流のポッドキャスト台本作家 |
| **呼び出し回数** | M 回（エピソード数） |
| **モデル設定** | Dramaturg モデル、temperature=0.7、num_ctx=32768 |
| **入力** | ペルソナ詳細、エピソード計画、概念の定義と原文引用、3幕構成指示 |
| **プロンプト** | 日本語のみで書くことを厳格に指示。原文引用を自分の言葉で言い換え。エピソード間の連続性維持 |
| **出力** | `ScriptV1` JSON |

### `translator/translator.py` — 日本語翻訳

| 項目 | 内容 |
|---|---|
| **LLM ロール** | 英日プロフェッショナル翻訳者 |
| **呼び出し回数** | S 回（翻訳ファイルのセクション数合計） |
| **モデル設定** | Translator モデル、temperature=0.1、num_ctx=8192 |
| **入力** | 英語マークダウンセクション（最大 3000 文字 / チャンク） |
| **翻訳対象** | `02_chunk_analyses.md`, `03_concept_graph.md`, `04_syllabus.md` |

---

## LLM 呼び出し回数の総計

| 構成 | Reader 呼び出し | Dramaturg 呼び出し | Translator 呼び出し |
|---|---|---|---|
| Route A + essence + skip-audio/translate | N + 2 | 1 | 0 |
| Route A + curriculum + 全ステージ | N + 2 | 6 | S |
| Route B + essence + skip-audio/translate | K + 3 | 1 | 0 |

- **N** = テキストチャンク数（通常 4〜8）
- **K** = 見出し数（通常 4〜8）
- **M** = エピソード数（essence=1, curriculum=3〜6）
- **S** = 翻訳セクション数（ファイル長に依存、通常 10〜30）

---

## JSON パース戦略

LLM からの JSON 抽出には `cogito/utils/logger.py` の `extract_json()` を使用:

1. ` ```json ... ``` ` コードフェンスを優先
2. ` ``` ... ``` ` フェンス（言語タグなし）
3. フォールバック: 最初の `{` から最後の `}` を抽出

Reader モデルには `format="json"` が必須（llama3 は前置きテキスト付きで返すことがある）。
Dramaturg モデルは JSON を含む自由形式テキストを生成するため `format="json"` を使わない。
