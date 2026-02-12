# ログファイル（Thinking Log）の解説

Cogito パイプラインの実行ログは `logs/run_YYYYMMDD_HHMMSS.json` に保存される。
このファイルには、システムが行った**全ての LLM 呼び出し（思考プロセス）**が記録されており、デバッグやプロンプトエンジニアリングの改善に不可欠な資料。

---

## ファイル構造

JSON ファイルのルートは `ThinkingLog` オブジェクト。

```json
{
  "run_id": "run_20260212_100013",
  "started_at": "2026-02-12T10:00:13.456789",
  "book_title": "Discourse on the Method",
  "mode": "essence",
  "steps": [
    { "timestamp": "...", "layer": "reader", "node": "analyst", ... },
    { "timestamp": "...", "layer": "reader", "node": "analyst", ... },
    ...
  ],
  "final_concept_graph": { ... },
  "final_syllabus": { ... }
}
```

| フィールド | 型 | 説明 |
|-----------|------|------|
| `run_id` | string | 実行 ID |
| `started_at` | string | 実行開始時刻（ISO 8601） |
| `book_title` | string | 対象書籍のタイトル |
| `mode` | string | 実行モード（essence / curriculum / topic） |
| `steps` | array | 思考ステップの配列（下記参照） |
| `final_concept_graph` | object / null | 最終的な統合コンセプトグラフ |
| `final_syllabus` | object / null | 最終的なシラバス |

---

## 各ステップの詳細フィールド

`steps` 配列の各要素が、パイプラインの1つの「思考ステップ」（= 1回の LLM 呼び出し）に対応する。

### 1. 識別情報

どのモジュールのどの処理かを特定する。

| フィールド | 例 | 説明 |
|-----------|-----|------|
| `timestamp` | `"2026-02-12T10:01:23.456"` | 実行時刻 |
| `layer` | `"reader"`, `"director"`, `"dramaturg"` | 担当レイヤー |
| `node` | `"analyst"`, `"synthesizer"`, `"scriptwriter"` | 担当モジュール |
| `action` | `"analyze_chunk:part_1"`, `"write_script:episode_1"` | 実行アクション名 |

### 2. 入力と推論

LLM に何を渡し、システムがどう判断したか。

| フィールド | 説明 |
|-----------|------|
| `input_summary` | 人間が読みやすい入力データの要約（例: `"Chunk 'part_1': 15000 chars"`） |
| `reasoning` | 処理完了後のシステムの要約コメント（例: `"Extracted 12 concepts from part_1"`） |

### 3. LLM との対話

**ここが最も重要。** LLM に実際に送られたプロンプトと、返ってきた生の回答。

| フィールド | 説明 |
|-----------|------|
| `llm_prompt` | **プロンプト全文**。変数が展開された後の、実際にモデルに入力されたテキスト |
| `llm_raw_response` | **モデルからの生テキスト**。JSON パースエラー時にモデルが実際に何を返したかを確認できる |

### 4. 解析結果

生のレスポンスからプログラムが抽出した構造化データ。

| フィールド | 説明 |
|-----------|------|
| `parsed_output` | JSON オブジェクト。パース成功時は構造化データ、失敗時はフォールバック値 |
| `error` | パースに失敗した場合のエラーメッセージ。成功時は `null` |

---

## 具体的な活用シナリオ

### シナリオA: 「台本が日本語になっていない」

1. ログファイルを開き、`"action": "write_script:episode_..."` を検索
2. `llm_prompt` を確認 — 「日本語で書いて」という指示が含まれているか？ペルソナ設定は正しく埋め込まれているか？
3. `llm_raw_response` を確認 — モデルが指示を無視しているのか、プロンプトが途切れているのか

### シナリオB: 「概念抽出の精度が低い」

1. `"node": "analyst"` のステップを検索
2. `llm_raw_response` でモデルの回答を確認
3. 説明が浅ければ、`src/reader/analyst.py` 内の `ANALYSIS_PROMPT` を修正する際の参考にする

### シナリオC: エラー原因の特定

1. ファイル内で `"error":` を検索し、`null` 以外の値を持つステップを見つける
2. そのステップの `llm_raw_response` で、JSON パース失敗の原因（途切れ、マークダウン混入等）を特定

---

## 閲覧のコツ

ログファイルは数万行に達することがある。以下が便利：

- **VS Code の折りたたみ（Fold）**: ステップごとに折りたたんで必要なステップだけ展開
- **jq での絞り込み**: `cat logs/run_*.json | jq '.steps[] | select(.error != null)'` でエラーステップだけ抽出
- **grep**: `grep -n '"action"' logs/run_*.json` でステップ一覧を取得
