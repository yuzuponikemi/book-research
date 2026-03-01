# デバッグガイド

パイプラインの問題を診断・修正するためのステップバイステップガイド。
各セクションは「症状 → 原因調査 → 修正」の流れで構成されている。

---

## 目次

1. [デバッグの基本ワークフロー](#基本ワークフロー)
2. [LLM 出力の問題](#llm-出力の問題)
3. [Ollama の問題](#ollama-の問題)
4. [チェックポイントと再開の問題](#チェックポイントの問題)
5. [VOICEVOX / 音声合成の問題](#voicevox-の問題)
6. [Web 検索の問題](#web-検索の問題)
7. [設定の問題](#設定の問題)
8. [品質の問題](#品質の問題)
9. [個別コンポーネントのテスト方法](#個別テスト)
10. [ログの分析テクニック](#ログ分析)

---

## 基本ワークフロー

### 1. 中間出力ファイルの確認

パイプラインが途中で失敗したり品質が低い場合、まず中間出力ファイルを確認する。

```bash
# 実行ディレクトリの内容確認
ls -la data/run_YYYYMMDD_HHMMSS/

# 各ステージの JSON を jq で整形して確認
cat data/run_YYYYMMDD_HHMMSS/03_concept_graph.json | python3 -m json.tool | head -50
```

**ファイルの存在チェック**: どのファイルまで生成されているかで、どのステージまで成功したかがわかる。

| ファイル | ステージ | ノード |
|---------|---------|------|
| `01_chunks.json` | テキスト取得 | `ingest` |
| `02_chunk_analyses.json` | 概念抽出 | `analyze_chunks` |
| `03_concept_graph.json` | グラフ合成 / Web研究 | `synthesize_graph` / `web_research` |
| `04_syllabus.json` | エピソード設計 | `produce` |
| `05_scripts.json` | 台本生成 | `produce` |
| `06_audio.json` | 音声合成 | `synthesize_audio` |

### 2. Thinking Log の確認

```bash
# エラーのあるステップを抽出
python3 -c "
import json
log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
for i, step in enumerate(log['steps']):
    if step.get('error'):
        print(f\"Step {i}: [{step['layer']}/{step['node']}] {step['action']}\")
        print(f\"  Error: {step['error']}\")
        print(f\"  Raw response (first 200): {step.get('llm_raw_response', '')[:200]}\")
        print()
"
```

### 3. 特定ステージからの再実行

```bash
# 中断したランをチェックポイントから再開
python -m cogito.orchestrator --resume run_YYYYMMDD_HHMMSS

# 既存の ConceptGraphV1 から Producer だけ再実行
python -m cogito.orchestrator \
    --from-graph data/run_YYYYMMDD_HHMMSS/03_concept_graph.json \
    --mode essence --persona socratic

# 各サービスを個別に再実行
python -m cogito.services.producer \
    --input  data/run_YYYYMMDD_HHMMSS/03_concept_graph.json \
    --output data/run_YYYYMMDD_HHMMSS/ \
    --mode   essence
```

---

## LLM 出力の問題

### 症状: JSON パースエラーが頻発する

**調査手順**:

1. Thinking Log でエラーを特定:

```bash
python3 -c "
import json
log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
errors = [s for s in log['steps'] if s.get('error') and 'JSON' in str(s.get('error', ''))]
print(f'{len(errors)} JSON errors found')
for s in errors:
    print(f\"  [{s['action']}] {s['error']}\")
    raw = s.get('llm_raw_response', '')
    print(f\"  Response starts with: {raw[:100]}...\")
    print()
"
```

2. LLM の生の出力を確認:

よくあるパターン:
- **テキストプリアンブル付き JSON**: `"Here is the analysis:\n{\"concepts\": [..."` → `extract_json()` で自動処理
- **JSON の途中で切れている**: context window 不足 → `num_ctx` を増やす
- **Markdown コードフェンス**: `` ```json ... ``` `` → `extract_json()` で自動処理
- **完全にテキストのみ**: format="json" が設定されていない → コードを確認

3. **修正方法**:

```bash
# より大きなモデルを使用（JSON の遵守率が高い）
python -m cogito.orchestrator --reader-model command-r ...

# Producer のみ再実行
python -m cogito.services.producer \
    --input data/run_.../03_concept_graph.json \
    --output data/run_.../ \
    --planner-model command-r
```

### 症状: LLM が指定した JSON 構造に従わない

**調査手順**:

1. 期待される構造と実際の出力を比較:

```bash
python3 -c "
import json
log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
for s in log['steps']:
    if s['action'] == 'synthesize_concept_graph':
        parsed = s.get('parsed_output', {})
        print('Keys:', list(parsed.keys()))
        print('Concepts:', len(parsed.get('concepts', [])))
        print('Relations:', len(parsed.get('relations', [])))
        print('Has core_frustration:', bool(parsed.get('core_frustration')))
"
```

2. フィールドが欠けている場合:
   - Pydantic バリデーションエラーとして `error` フィールドに記録される
   - フォールバック値が使用されるため、下流のステージの品質が低下する

**修正方法**: プロンプトの JSON スキーマ指定を見直すか、より大きなモデルを使用。

### 症状: Pydantic バリデーションエラー

**調査手順**:

```bash
python3 -c "
import json
log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
for s in log['steps']:
    if s.get('error') and 'Validation' in str(s.get('error', '')):
        print(f\"[{s['action']}] {s['error']}\")
        parsed = s.get('parsed_output', {})
        for k, v in parsed.items():
            print(f\"  {k}: {type(v).__name__} = {str(v)[:80]}\")
"
```

**よくあるバリデーションエラー**:

| エラー | 原因 | 対策 |
|--------|------|------|
| `field required` | LLM が必須フィールドを省略 | プロンプトで JSON 構造を再度明示 |
| `value is not a valid list` | LLM が配列の代わりに文字列を返した | フォールバック値で処理継続 |
| `relation_type` 不正値 | LLM が `related_to` 等を返した（既知の問題） | `synthesizer.py` の `from_legacy_dict` でフィルタ済み |
| `episodes: non-dict items` | LLM がリストに文字列を混入 | `planner.py` のフィルタで除去 |

---

## Ollama の問題

### 症状: LLM コールがハングする（応答が返らない）

**原因の特定**:

```bash
# Ollama のプロセス確認
ps aux | grep ollama

# Ollama のログ確認（macOS）
tail -f ~/.ollama/logs/server.log
```

**主な原因と対策**:

| 原因 | 症状 | 対策 |
|------|------|------|
| モデルがアンロードされた | 長い推論中にタイムアウト | `OLLAMA_KEEP_ALIVE=120m` で起動 |
| 並行リクエスト | Apple Silicon でデッドロック | `OLLAMA_NUM_PARALLEL=1` で起動 |
| Context overflow | 入力がモデルの context window を超過 | `num_ctx` を確認（llama3: 8K, command-r: 128K） |
| メモリ不足 | qwen3-next (50GB) が VRAM に収まらない | より小さなモデルを使用 |

**正しい起動方法**:

```bash
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

**ハング時のリカバリ**:

1. `Ctrl-C` でパイプラインを停止（チェックポイントは自動保存）
2. Ollama を再起動:
   ```bash
   pkill ollama
   OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
   ```
3. パイプラインを再開:
   ```bash
   python -m cogito.orchestrator --resume run_YYYYMMDD_HHMMSS
   ```

### 症状: "Connection refused" エラー

```bash
# Ollama が起動しているか確認
curl http://localhost:11434/api/tags

# 起動していない場合
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve
```

### 症状: モデルが見つからない

```bash
# インストール済みモデルの確認
ollama list

# 必要なモデルをインストール
ollama pull llama3
ollama pull qwen3-next
ollama pull command-r
ollama pull translategemma:12b
```

---

## チェックポイントの問題

### 症状: --resume が機能しない

**調査手順**:

1. チェックポイント DB の存在確認:

```bash
ls -la data/checkpoints.db
```

2. SQLite DB の内容確認:

```bash
sqlite3 data/checkpoints.db \
  "SELECT DISTINCT thread_id FROM checkpoints;"
# 期待値: "run_YYYYMMDD_HHMMSS"（各 run_id がスレッドとして保存される）
```

3. チェックポイントの最新状態を確認:

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("data/checkpoints.db")
saver = SqliteSaver(conn)
config = {"configurable": {"thread_id": "run_YYYYMMDD_HHMMSS"}}
checkpoint = saver.get(config)
if checkpoint:
    print("Checkpoint found")
    print("Keys in state:", list(checkpoint.get("channel_values", {}).keys()))
else:
    print("No checkpoint found")
conn.close()
```

**主な原因**:

| 原因 | 対策 |
|------|------|
| `data/checkpoints.db` が存在しない | パイプラインが 1 ノードも完了していない |
| run_id が不一致 | `--resume` に渡す run_id を確認（`data/` ディレクトリ名から） |
| DB が壊れている | 最初から再実行 |

### 症状: 有効なノード名がわからない

**新アーキテクチャのノード名**:

```
ingest, analyze_chunks, synthesize_graph, web_research,
produce, synthesize_audio, check_translate, translate
```

`--from-graph` オプションで `synthesize_graph` / `web_research` をスキップし、`produce` から直接開始できる。

---

## VOICEVOX の問題

### 症状: "VOICEVOX engine not running" と表示される

```bash
# VOICEVOX アプリを起動
open -a VOICEVOX

# エンジンの接続テスト
curl http://localhost:50021/version
```

**注意**: VOICEVOX アプリを起動してからエンジンが利用可能になるまで数秒かかる場合がある。

### 症状: 特定の話者 ID でエラーが出る

```bash
# 利用可能な話者を確認
python3 -m cogito.services.audio.voicevox_client --list-speakers

# テスト合成
python3 -m cogito.services.audio.voicevox_client "テスト" --speaker 0
```

**話者 ID の解決順序** (`synthesizer.py`):

1. `persona_config["voice"]` の名前→ID マッピングで完全一致を検索
2. ペルソナ名と一致する場合、`_default_a` / `_default_b` にフォールバック
3. 最終フォールバック: speaker ID 0

### 症状: MP3 ファイルが生成されない / 空の音声

**調査手順**:

```bash
# audio_metadata を確認
cat data/run_YYYYMMDD_HHMMSS/06_audio.json | python3 -m json.tool

# errors の数を確認
python3 -c "
import json
meta = json.load(open('data/run_.../06_audio.json'))
for m in meta:
    print(f\"Ep{m['episode_number']}: {m['lines_synthesized']} lines, {m['errors']} errors, {m['duration_sec']}s\")
"
```

**主な原因**:

| 原因 | 症状 | 対策 |
|------|------|------|
| VOICEVOX 未起動 | 全エピソードの file が null | VOICEVOX を起動 |
| 台本の dialogue が空 | lines_synthesized = 0 | scripts の品質を確認 |
| 特定行の合成失敗 | errors > 0 | 台本に不正な文字（絵文字等）がないか確認 |
| pydub / audioop エラー | ImportError | `pip install audioop-lts` |

### 症状: pydub が audioop を見つけられない

Python 3.13+ では `audioop` モジュールが標準ライブラリから削除された。

```bash
pip install audioop-lts
```

### 無音の長さを調整したい

`cogito/services/audio/synthesizer.py` の定数:

```python
SILENCE_SAME_SPEAKER_MS = 600   # 同一話者の発言間
SILENCE_SPEAKER_CHANGE_MS = 800  # 話者交代時
SILENCE_SECTION_MS = 1800        # opening_bridge/closing_hook の前後
```

---

## Web 検索の問題

### 症状: Web 検索結果が 0 件

**調査手順**:

```bash
# Tavily API キーの確認
echo $TAVILY_API_KEY

# 個別エンジンのテスト
python -m cogito.services.web_researcher.web_search --engine tavily "Descartes Discourse"
python -m cogito.services.web_researcher.web_search --engine duckduckgo "Descartes Discourse"
python -m cogito.services.web_researcher.web_search "Descartes Discourse"
```

**エンジン選択の優先順位** (`web_search.py`):

1. Tavily（`TAVILY_API_KEY` が設定されている場合）
2. DuckDuckGo（`ddgs` パッケージ）
3. なし（空の結果で処理続行）

**修正方法**:

```bash
# Tavily の設定
export TAVILY_API_KEY=tvly-xxxxx

# DuckDuckGo のインストール
pip install ddgs
```

---

## 設定の問題

### 症状: "Book config not found" エラー

```bash
# 利用可能な書籍設定を確認
ls config/books/

# 設定ファイルのバリデーション
python3 -c "
from cogito.config.book_config import load_book_config
try:
    cfg = load_book_config('my_book')
    print('Valid!')
    print('Title:', cfg['book']['title'])
except Exception as e:
    print(f'Error: {e}')
"
```

### 症状: "Unknown persona preset" エラー

```bash
# 利用可能なペルソナを確認
python3 -c "
import yaml
with open('config/personas.yaml') as f:
    cfg = yaml.safe_load(f)
print('Available presets:', list(cfg['presets'].keys()))
"
```

### 症状: テンプレート変数が展開されない

検索クエリに `{author}` 等がそのまま残っている場合:

```bash
# テンプレート解決の確認
python3 -c "
from cogito.config.book_config import load_book_config
cfg = load_book_config('descartes_discourse')
print('Search queries:')
for q in cfg['research']['search_queries']:
    print(f'  {q}')
"
```

**利用可能なテンプレート変数**: `{author}`, `{title}`, `{author_ja}`, `{title_ja}`, `{year}`

### 症状: インポートエラー

```bash
# モジュールの一括確認
python3 -c "
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

## 品質の問題

### 症状: 概念抽出の品質が低い（浅い説明、少ない概念）

**調査手順**:

1. チャンク分析の結果を確認:

```bash
python3 -c "
import json
analyses = json.load(open('data/run_.../02_chunk_analyses.json'))
for i, a in enumerate(analyses):
    n_c = len(a.get('concepts', []))
    n_a = len(a.get('aporias', []))
    n_r = len(a.get('relations', []))
    print(f'Chunk {i+1}: {n_c} concepts, {n_a} aporias, {n_r} relations')
    descs = [len(c.get('description', '')) for c in a.get('concepts', []) if isinstance(c, dict)]
    if descs:
        print(f'  Avg description length: {sum(descs)/len(descs):.0f} chars')
"
```

2. 入力テキストの品質を確認:

```bash
python3 -c "
import json
chunks_data = json.load(open('data/run_.../01_chunks.json'))
for chunk in chunks_data['chunks']:
    print(f\"Chunk {chunk['id']}: {len(chunk['text'])} chars\")
"
```

**対策**:

| 原因 | 対策 |
|------|------|
| モデルが小さい（llama3 4.7GB） | `--reader-model command-r` に変更 |
| チャンクが大きすぎる | チャンク分割の regex を調整 |
| チャンクが小さすぎる | 同上 |
| key_terms が設定されていない | `config/books/*.yaml` の `context.key_terms` に追加 |

### 症状: 台本が日本語になっていない（英語が混入）

**調査手順**:

```bash
python3 -c "
import json
log = json.load(open('logs/run_.../run_....json'))
for s in log['steps']:
    if s['action'].startswith('write_script'):
        prompt = s.get('llm_prompt', '')
        has_ja = '日本語' in prompt
        print(f\"{s['action']}: 日本語指示={has_ja}\")
        raw = s.get('llm_raw_response', '')
        ascii_ratio = sum(1 for c in raw if ord(c) < 128) / max(len(raw), 1)
        print(f'  ASCII ratio: {ascii_ratio:.1%} (high = mostly English)')
"
```

**対策**:

| 原因 | 対策 |
|------|------|
| 使用モデルの日本語能力が低い | `--dramaturg-model qwen3-next` に変更 |
| ペルソナ設定が英語 | `config/personas.yaml` のペルソナ説明を日本語にする |
| 概念テキストが英語 | 正常な挙動（概念は英語で抽出され、台本生成時に日本語化される） |

### 症状: 台本の発言数が少ない

```bash
python3 -c "
import json
scripts = json.load(open('data/run_.../05_scripts.json'))
for s in scripts:
    n = len(s.get('dialogue', []))
    print(f'Episode {s.get(\"episode_number\")}: {n} lines ({\"OK\" if 50 <= n <= 65 else \"LOW\" if n < 50 else \"HIGH\"})')
"
```

**対策**: temperature を上げる（現在 0.7）、`num_ctx` を増やす、プロンプトの品質基準を強化。

---

## 個別テスト

### Web 検索のテスト

```bash
# Tavily
python -m cogito.services.web_researcher.web_search --engine tavily "Descartes Discourse"

# DuckDuckGo
python -m cogito.services.web_researcher.web_search --engine duckduckgo "Descartes biography"

# 自動選択
python -m cogito.services.web_researcher.web_search "Descartes Discourse on Method"
```

### VOICEVOX のテスト

```bash
# 接続確認
curl http://localhost:50021/version

# 話者一覧
python3 -m cogito.services.audio.voicevox_client --list-speakers

# テスト合成
python3 -m cogito.services.audio.voicevox_client "テストです" --speaker 0
# → test_output.wav が生成される
```

### 書籍設定のバリデーション

```bash
python3 -c "
from cogito.config.book_config import load_book_config
cfg = load_book_config('descartes_discourse')
print('Title:', cfg['book']['title'])
print('Source type:', cfg['source']['type'])
print('Chunking:', cfg['chunking']['strategy'])
print('Search queries:', cfg['research']['search_queries'])
print('Key terms:', cfg['context']['key_terms'])
"
```

### 単一チャンクの分析テスト

```bash
python3 -c "
from langchain_ollama import ChatOllama
from cogito.services.analyst.extractor import analyze_chunk

llm = ChatOllama(model='llama3', temperature=0.1, num_ctx=16384, format='json')
text = 'Good sense is, of all things among men, the most equally distributed...'
result, step = analyze_chunk(text, 'TEST', llm, key_terms=['Methodical Doubt'])
print(f'Concepts: {len(result.get(\"concepts\", []))}')
print(f'Error: {step.get(\"error\")}')
"
```

### LLM の直接テスト

```bash
# Ollama CLI で直接テスト
ollama run llama3 'Return a JSON object with key "hello" and value "world"'

# Python で ChatOllama をテスト
python3 -c "
from langchain_ollama import ChatOllama
llm = ChatOllama(model='llama3', temperature=0.1, format='json')
result = llm.invoke('Return JSON: {\"test\": true}')
print(result.content)
"
```

### チェックポイントの状態確認

```bash
python3 -c "
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect('data/checkpoints.db')
saver = SqliteSaver(conn)
config = {'configurable': {'thread_id': 'run_YYYYMMDD_HHMMSS'}}

state = saver.get(config)
if state:
    values = state.get('channel_values', {})
    print('State keys:', list(values.keys()))
    print('Scripts:', len(values.get('scripts', [])))
else:
    print('No checkpoint found')
conn.close()
"
```

---

## ログ分析

### 全ステップの一覧表示

```bash
python3 -c "
import json
log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
for i, step in enumerate(log['steps']):
    err = ' [ERROR]' if step.get('error') else ''
    print(f'{i:3d}. [{step[\"layer\"]}/{step[\"node\"]}] {step[\"action\"]}{err}')
"
```

### 特定ノードのプロンプトと応答を確認

```bash
python3 -c "
import json
log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
for s in log['steps']:
    if s['action'] == 'synthesize_concept_graph':  # 確認したいアクション名
        print('=== PROMPT (first 1000 chars) ===')
        print(s.get('llm_prompt', '')[:1000])
        print()
        print('=== RAW RESPONSE (first 1000 chars) ===')
        print(s.get('llm_raw_response', '')[:1000])
        print()
        print('=== ERROR ===')
        print(s.get('error'))
"
```

### LLM コールの所要時間を推定

```bash
python3 -c "
import json
from datetime import datetime

log = json.load(open('logs/run_YYYYMMDD_HHMMSS.json'))
steps = log['steps']

for i in range(len(steps) - 1):
    t1 = datetime.fromisoformat(steps[i]['timestamp'])
    t2 = datetime.fromisoformat(steps[i+1]['timestamp'])
    delta = (t2 - t1).total_seconds()
    if delta > 10:  # 10秒以上のステップのみ表示
        print(f'{delta:6.1f}s  [{steps[i][\"layer\"]}/{steps[i][\"node\"]}] {steps[i][\"action\"]}')
"
```

### jq を使ったフィルタリング

```bash
# エラーのあるステップだけ抽出
cat logs/run_*.json | jq '.steps[] | select(.error != null) | {action, error}'

# analyze_chunk のステップだけ抽出
cat logs/run_*.json | jq '.steps[] | select(.action | startswith("analyze_chunk")) | {action, reasoning}'

# 全ステップのアクション名一覧
cat logs/run_*.json | jq '[.steps[].action]'
```

---

## LLM コール箇所の早引き表

ソースコード内の全 LLM 呼び出し箇所。デバッグ時のブレークポイント設置の参照用。

| ファイル | 呼び出し | モデル | format |
|---------|---------|-------|--------|
| `cogito/services/analyst/extractor.py` | `analyze_chunk` | Reader | json |
| `cogito/services/analyst/synthesizer.py` | `synthesize_graph` | Reader | json |
| `cogito/services/web_researcher/planner.py` | `plan_headings` | Reader | json |
| `cogito/services/web_researcher/searcher.py` | `generate_queries` | Reader | json |
| `cogito/services/web_researcher/aggregator.py` | `aggregate_results` | Reader | json |
| `cogito/services/web_researcher/synthesizer.py` | `synthesize_graph` | Reader | json |
| `cogito/services/producer/planner.py` | `plan_syllabus` | Reader | json |
| `cogito/services/producer/podcast.py` | `write_script` | Dramaturg | なし |
| `cogito/services/translator/translator.py` | `translate_section` | Translator | なし |

### 外部 API コール箇所

| ファイル | API | 説明 |
|---------|-----|------|
| `cogito/services/web_researcher/web_search.py` | Tavily | `client.search(query)` |
| `cogito/services/web_researcher/web_search.py` | DuckDuckGo | `ddgs.text(query)` |
| `cogito/services/audio/voicevox_client.py` | VOICEVOX | `GET /version`, `POST /audio_query`, `POST /synthesis` |
| `cogito/services/ingestor/adapters/book.py` | HTTP | `httpx.get(url)` テキストダウンロード |
| `cogito/services/ingestor/adapters/arxiv_client.py` | ar5iv | arXiv フルテキスト取得 |
