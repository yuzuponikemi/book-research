# Project Cogito - パイプラインガイド

## クイックスタート

```bash
# 仮想環境を有効化
source .venv/bin/activate

# デフォルト設定で実行（essenceモード、descartes_defaultペルソナ）
python3 main.py

# オプションを指定して実行
python3 main.py --mode curriculum --persona socratic
python3 main.py --mode topic --topic "cogito ergo sum" --persona debate

# 別のOllamaモデルを指定
python3 main.py --reader-model command-r --dramaturg-model qwen3-next

# 翻訳モデルを指定（デフォルト: translategemma:12b）
python3 main.py --translator-model translategemma:12b

# 翻訳ステップをスキップ
python3 main.py --skip-translate
```

### CLIオプション

| フラグ | デフォルト | 説明 |
|---|---|---|
| `--mode` | `essence` | `essence`（1話、核心のアイデア）、`curriculum`（4-6話の連続講義）、`topic`（特定テーマに集中） |
| `--persona` | `descartes_default` | `config/personas.yaml` のペルソナプリセット名 |
| `--topic` | - | `topic` モードで必須 |
| `--reader-model` | `llama3` | 分析・計画用のOllamaモデル（JSON出力能力が必要） |
| `--dramaturg-model` | `qwen3-next` | 日本語対話生成用のOllamaモデル |
| `--translator-model` | `translategemma:12b` | 中間出力の日本語翻訳用モデル |
| `--skip-translate` | - | 翻訳ステップをスキップ |
| `--skip-research` | - | 研究・批評・統合ステージをスキップ |
| `--skip-audio` | - | VOICEVOX 音声合成をスキップ |
| `--trace` | - | Arize Phoenix のローカル UI を起動し、全 LLM 呼び出しをトレース |
| `--resume` | - | 前回実行のチェックポイントから再開（run ID を指定） |
| `--from-node` | - | 指定ノード以降を再実行（`--resume` 必須） |

---

## パイプラインの全体像

Project Cogitoは、哲学的テキストを分析し、ポッドキャスト台本に変換するパイプラインです。
3つのレイヤー（Reader・Director・Dramaturg）が順に処理を行います。

```
テキスト取得 → 概念抽出 → 統合 → カリキュラム設計 → 台本生成 → 日本語翻訳
  (Stage 1)   (Stage 2)  (Stage 3)  (Stage 4)       (Stage 5)    (Stage 6)
   Reader層     Reader層   Reader層   Director層    Dramaturg層   Translator
```

各ステージの出力は、人間が読める `.md` ファイルと機械可読の `.json` ファイルとして保存されます。

```
data/run_YYYYMMDD_HHMMSS/
  01_chunks.md              <- テキストチャンク
  01_chunks.json
  02_chunk_analyses.md      <- チャンクごとの概念抽出（英語）
  02_chunk_analyses_ja.md   <- チャンクごとの概念抽出（日本語）
  02_chunk_analyses.json
  03_concept_graph.md       <- 統合コンセプトグラフ（英語）
  03_concept_graph_ja.md    <- 統合コンセプトグラフ（日本語）
  03_concept_graph.json
  04_syllabus.md            <- エピソード計画（英語）
  04_syllabus_ja.md         <- エピソード計画（日本語）
  04_syllabus.json
  05_scripts.md             <- 最終対話台本（日本語）
  05_scripts.json

logs/run_YYYYMMDD_HHMMSS.json  <- 思考ログ（全LLMプロンプト・レスポンス）
```

---

## 各ステージの詳細

### ステージ1: テキスト取得 (`01_chunks`)

**処理内容:** Project Gutenbergからデカルトの『方法序説』原文（英訳）をダウンロードし、
ヘッダー・フッターを除去した上で、PART I〜PART VIの6つのセマンティックチャンクに分割します。

**確認ポイント:**
- 全6パートが正しく分割されているか
- 各チャンクのサイズは適切か（PART I: 約15,000文字、PART V: 約32,000文字）
- `01_chunks.md` を開いて各チャンクのプレビューを確認

**LLM呼び出し:** なし（決定論的なテキスト処理のみ）

### ステージ2: 概念抽出 (`02_chunk_analyses`)

**処理内容:** 各チャンクをReaderモデル（デフォルト: llama3）に送り、解釈学的分析プロンプトで
概念（concepts）、アポリア（未解決の緊張）、概念間の関係、論理の流れを抽出します。

**確認ポイント（`02_chunk_analyses_ja.md`）:**
- 各チャンクに概念が抽出されているか（チャンクごとに5-10個が期待値）
- 抽出された概念は「要約」ではなく「哲学的概念」か
- PART IVに `cogito_ergo_sum`（我思う、故に我あり）や `methodical_doubt`（方法的懐疑）が含まれるか
- 引用は原文からの正確なものか（ハルシネーションでないか）
- 関係性は妥当か（例: `methodical_doubt` → `cogito_ergo_sum`）

**よくある問題:**
- あるチャンクの概念数が0 → JSON解析の失敗。思考ログの `llm_raw_response` を確認
- 概念が浅い → モデルが小さすぎる。`--reader-model command-r` を試す

### ステージ3: 統合 (`03_concept_graph`)

**処理内容:** 6つのチャンク分析を1つの統合コンセプトグラフにマージします。
チャンク間で重複する概念を統合し、チャンク横断の関係を構築し、
テキスト全体を貫く `core_frustration`（核心的なフラストレーション）を特定します。

**確認ポイント（`03_concept_graph_ja.md`）:**
- チャンク間の重複概念が統合されているか（例: `methodical_doubt` はParts I, II, IV, VIに
  出現するが、統合グラフでは1つにまとまるべき）
- `core_frustration` は汎用的な要約ではなく、真の知的緊張を表しているか
- `logic_flow` はPART IからPART VIまでの一貫した物語を語っているか
- チャンク横断の関係が存在するか（例: Part Iの懐疑 → Part IVのコギト）

**デカルト『方法序説』で期待される主要概念:**
- 方法的懐疑（methodical doubt）
- 我思う、故に我あり（cogito ergo sum）
- 明晰判明の規則（clear and distinct perception）
- 心身二元論（mind-body dualism）
- 神の存在証明（proof of God's existence）

### ステージ4: カリキュラム設計 (`04_syllabus`)

**処理内容:** モードに基づいてエピソード計画を生成します。

| モード | エピソード数 | 説明 |
|---|---|---|
| `essence` | 1話 | 核心的な緊張を捉える |
| `curriculum` | 4-6話 | アイデアの論理的進行に沿って展開 |
| `topic` | 1-2話 | 特定のトピックに集中 |

**確認ポイント（`04_syllabus_ja.md`）:**
- `cognitive_bridge`（認知的ブリッジ）が17世紀の哲学と現代生活を接続しているか
- `concept_ids` と `aporia_ids` がコンセプトグラフの実際のIDを参照しているか
- `cliffhanger` が次のエピソードを聴きたくなる問いかけになっているか
- エピソード間で概念の依存関係が尊重されているか

**注意:** Plannerの出力は英語で生成されます（command-rが日本語を正しく生成できないため）。
日本語版は翻訳ステージ（Stage 6）で生成されます。

### ステージ5: 台本生成 (`05_scripts`)

**処理内容:** 選択されたペルソナプリセットとDramaturgモデル（デフォルト: qwen3-next）を使い、
日本語の対話台本を生成します。各エピソードは3幕構成で、50-65発言を目標とします。

**3幕構成:**
1. **第1幕: 導入と問題提起（約3分）** - 現代の具体例から哲学的問いを引き出す
2. **第2幕: 哲学的掘り下げ（約5分）** - 原著の概念を丁寧に掘り下げ、引用を織り込む
3. **第3幕: 統合と余韻（約2分）** - 議論をまとめ、リスナーに問いを残す

**確認ポイント（`05_scripts.md`）:**
- 対話は自然な日本語か（翻訳調になっていないか）
- 二人のキャラクターの声やトーンが区別できるか
- デカルトの原文引用が自然に織り込まれているか
- `opening_bridge` が文脈を設定し、`closing_hook` が期待を高めているか
- 第1話が『方法序説』の紹介から始まっているか（「前回」への言及がないか）
- この対話が『方法序説』の解説であることが聴き手に明確に伝わるか

**ペルソナの違い:** `--persona` の値によって対話スタイルが大きく変わります:
- `descartes_default`: 現代の懐疑論者 vs. デカルトの亡霊
- `socratic`: 哲学初心者の学生 vs. ソクラテス的メンター
- `debate`: 情熱的な擁護者 vs. 厳格な批判者

### ステージ6: 日本語翻訳

**処理内容:** TranslateGemma 12Bを使用して、英語で生成された中間出力（チャンク分析、
コンセプトグラフ、シラバス）を日本語に翻訳します。

**翻訳対象:**
- `02_chunk_analyses.md` → `02_chunk_analyses_ja.md`
- `03_concept_graph.md` → `03_concept_graph_ja.md`
- `04_syllabus.md` → `04_syllabus_ja.md`

**注意:** 台本（`05_scripts.md`）は最初から日本語で生成されるため、翻訳対象外です。
チャンク（`01_chunks.md`）はデカルトの原文であり、翻訳は行いません。

`--skip-translate` フラグで翻訳ステップをスキップできます。

---

## LLM トレーシング（Arize Phoenix）

`--trace` フラグを付けると、ローカルに Arize Phoenix UI が起動し、全 LLM 呼び出しの入出力・レイテンシをリアルタイムで可視化できます。

```bash
python3 main.py --mode essence --trace
```

起動後、ターミナルに表示される URL（通常 `http://localhost:6006`）をブラウザで開くと、各ステージ（analyst, synthesizer, planner 等）のスパンがトレースとして表示されます。デバッグや性能分析に便利です。

---

## 思考ログ（Thinking Log）

`logs/run_YYYYMMDD_HHMMSS.json` に、パイプラインの全決定過程が記録されます。
各ステップには以下の情報が含まれます:

```json
{
  "timestamp": "2026-02-09T01:01:31.123456",
  "layer": "reader",
  "node": "analyst",
  "action": "analyze_chunk:PART IV",
  "input_summary": "Chunk 'PART IV': 15597 chars",
  "llm_prompt": "You are a philosopher performing hermeneutic analysis...",
  "llm_raw_response": "{ \"concepts\": [...] }",
  "parsed_output": { ... },
  "error": null,
  "reasoning": "Extracted 5 concepts, 1 aporias, 3 relations from PART IV"
}
```

### 概念の追跡方法

1. `03_concept_graph.json` で対象の概念を見つける（例: `cogito_ergo_sum`）
2. `source_chunk` を確認する（例: `PART IV`）
3. 思考ログを開き、`action: "analyze_chunk:PART IV"` のステップを見つける
4. `llm_prompt` でモデルに送られた正確なプロンプトを確認
5. `llm_raw_response` でモデルの生の出力を確認
6. `parsed_output` と比較して、解析で情報が失われていないか確認

### 概念が欠落している場合のデバッグ

1. `02_chunk_analyses.json` を確認 - チャンクレベルで概念が抽出されていたか？
   - 抽出されていない場合: アナリストのプロンプト調整が必要、またはチャンクが切り詰められている
   - 抽出されていた場合: シンセサイザーが統合時にマージしてしまった。ログのシンセサイザーステップを確認
2. シンセサイザーステップの `llm_raw_response` でマージの判断内容を確認

---

## モデル選択ガイド

| 役割 | 推奨 | 最低要件 | 備考 |
|---|---|---|---|
| Reader/Director | `command-r` (18GB) | `llama3` (4.7GB) | 大きいほど概念抽出の質が向上 |
| Dramaturg | `qwen3-next` (50GB) | `llama3` (4.7GB) | Qwenモデルは日本語に優れる |
| Translator | `translategemma:12b` | - | Google TranslateGemma、55言語対応 |

**Reader/Directorモデル** はJSON出力が必須のため、`format="json"` が有効化されています。
**Dramaturgモデル** はJSON構造を含む自由形式テキストを生成するため、JSONモードは強制しません。
**Translatorモデル** は翻訳専用で、特別なプロンプト形式を使用します。

**注意:** PlannerステージはReaderモデル（command-r）を使用しますが、日本語生成の品質問題を
避けるため、全出力を英語で生成します。日本語版はTranslateGemmaによる翻訳で提供されます。

---

## ペルソナ設定

`config/personas.yaml` を編集して、新しいペルソナプリセットの作成や既存プリセットの
変更ができます。各プリセットは2つのキャラクター（`persona_a` と `persona_b`）を定義します:

- `name`: 対話で使用されるキャラクター名
- `role`: 役割の説明（日本語）
- `description`: キャラクターの詳細な説明
- `tone`: 話し方のトーン（日本語）
- `speaking_style`: キャラクターの話し方のスタイル

ペルソナの記述はDramaturgのプロンプトに直接注入されます。
日本語と英語を混ぜて記述すると効果的です。日本語の部分がモデルの出力トーンを誘導し、
英語の部分が明確な指示を提供します。

### 利用可能なプリセット

| プリセット名 | persona_a | persona_b | スタイル |
|---|---|---|---|
| `descartes_default` | Host（現代の懐疑論者） | Descartes（哲学者の亡霊） | 現代的なアナロジーで哲学を語る |
| `socratic` | Student（哲学初心者） | Mentor（哲学の案内人） | ソクラテス式問答法 |
| `debate` | Advocate（著者の擁護者） | Critic（批判的検証者） | 弁証法的な激しい議論 |

---

## トラブルシューティング

### 概念が0個のチャンクがある
- **原因:** LLMのJSON出力が不正。テキストの前置きが含まれている可能性。
- **対策:** 思考ログの `llm_raw_response` を確認。`format="json"` がChatOllamaで有効か確認。

### シンセサイザーが概念を過度に圧縮する
- **原因:** 小さいモデル（llama3）は概念を4-5個に圧縮しがち。
- **対策:** `--reader-model command-r` で大きなモデルを使用。

### Plannerの出力が文字化けしている
- **原因:** command-rは日本語生成が不安定。
- **対策:** Plannerは英語出力に設定済み。翻訳ステージで日本語版を生成。

### 対話の行数が目標（50-65行）に届かない
- **原因:** qwen3-nextの生成傾向として、プロンプトの目標行数より少なく終わることがある。
- **対策:** 今後の改善で、マルチパス生成（生成後に拡張）を検討。

### Python関連
- `python` コマンドが見つからない場合は `python3` を使用（Python 3.14環境）
- `langchain_core` のPydantic V1非推奨警告は無害（Python 3.14との互換性問題）
