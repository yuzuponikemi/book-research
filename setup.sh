#!/usr/bin/env bash
# setup.sh — book-research 依存パッケージのインストールスクリプト
# パッケージは /workspace/group/.pypackages にインストールされる

set -e

PYPACKAGES="/workspace/group/.pypackages"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== book-research setup ==="
echo "パッケージインストール先: $PYPACKAGES"
mkdir -p "$PYPACKAGES"

# ---------------------------------------------------------------------------
# 1. pip のブートストラップ（必要な場合）
# ---------------------------------------------------------------------------
echo ""
echo "[1/4] pip のブートストラップ..."
curl -sS https://bootstrap.pypa.io/get-pip.py | python3 - --target "$PYPACKAGES" -q
echo "  pip インストール完了"

# ---------------------------------------------------------------------------
# 2. requirements.txt からパッケージをインストール
#    audioop-lts は Python 3.13 以降でのみ必要なため除外
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] requirements.txt からパッケージをインストール中..."
PYTHONPATH="$PYPACKAGES" python3 -m pip install \
    $(grep -v audioop-lts "$SCRIPT_DIR/requirements.txt" | tr '\n' ' ') \
    --target "$PYPACKAGES" -q
echo "  パッケージインストール完了"

# ---------------------------------------------------------------------------
# 3. langgraph-checkpoint-sqlite を手動展開
#    --target を使うと名前空間パッケージが壊れるため wheel を直接展開する
# ---------------------------------------------------------------------------
echo ""
echo "[3/4] langgraph-checkpoint-sqlite を手動インストール中..."
PYTHONPATH="$PYPACKAGES" python3 -m pip download langgraph-checkpoint-sqlite \
    -d /tmp/lgcsqlite --no-deps -q

python3 -c "
import zipfile, shutil, os
whl = next(__import__('pathlib').Path('/tmp/lgcsqlite').glob('*.whl'))
target = '$PYPACKAGES'
print(f'  展開中: {whl.name}')
with zipfile.ZipFile(str(whl)) as z:
    for name in z.namelist():
        if name.startswith('langgraph/') and '.dist-info' not in name:
            dest = os.path.join(target, name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not name.endswith('/'):
                with z.open(name) as src, open(dest, 'wb') as dst:
                    __import__('shutil').copyfileobj(src, dst)
print('  langgraph-checkpoint-sqlite 展開完了')
"

# ---------------------------------------------------------------------------
# 4. 主要インポートの動作確認
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] インポート確認..."
PYTHONPATH="$PYPACKAGES" python3 -c "
import sys
checks = [
    ('langgraph', 'langgraph'),
    ('langgraph.checkpoint.sqlite', 'langgraph-checkpoint-sqlite'),
    ('langchain_ollama', 'langchain-ollama'),
    ('yaml', 'PyYAML'),
]
failed = []
for module, pkg in checks:
    try:
        __import__(module)
        print(f'  OK  {pkg}')
    except ImportError as e:
        print(f'  NG  {pkg}: {e}')
        failed.append(pkg)
if failed:
    print(f'警告: {len(failed)} パッケージのインポートに失敗しました: {failed}')
    sys.exit(1)
else:
    print('  すべてのインポート確認OK')
"

# ---------------------------------------------------------------------------
# .env のセットアップ
# ---------------------------------------------------------------------------
echo ""
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo ".env を .env.example からコピーしました"
        echo "必要に応じて $SCRIPT_DIR/.env を編集してください"
    else
        echo ".env.example が見つかりません。.env は作成しませんでした"
    fi
else
    echo ".env はすでに存在します（スキップ）"
fi

# ---------------------------------------------------------------------------
# 使い方の案内
# ---------------------------------------------------------------------------
echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "使い方:"
echo "  PYTHONPATH=$PYPACKAGES python3 run_pipeline.py --book デカルト --chat-jid tg:-5218254973"
echo "  PYTHONPATH=$PYPACKAGES python3 run_pipeline.py --book attention --chat-jid tg:-5218254973 --full"
echo ""
echo "Ollama モデル設定: $SCRIPT_DIR/config/ollama_models.yaml"
echo "Ollama 接続確認:   curl http://host.docker.internal:11434/api/tags"
