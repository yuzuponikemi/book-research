"""Streamlit Web UI for Project Cogito."""

import json
import subprocess
import sys
import time
from pathlib import Path
import streamlit as st

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))
BOOK_RESEARCH_DIR = Path(__file__).parent.parent
DATA_DIR = BOOK_RESEARCH_DIR / "data"
CONFIG_DIR = BOOK_RESEARCH_DIR / "config" / "books"

PYPACKAGES = "/workspace/group/.pypackages"
if PYPACKAGES not in sys.path:
    sys.path.insert(0, PYPACKAGES)

st.set_page_config(page_title="Project Cogito", page_icon="📚", layout="wide")

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("📚 Project Cogito")
st.sidebar.caption("哲学書 → ポッドキャストスクリプト生成")

# Book selection
book_configs = sorted(CONFIG_DIR.glob("*.yaml"))
book_names = [f.stem for f in book_configs]
selected_book = st.sidebar.selectbox("書籍を選択", book_names, index=0 if book_names else None)

mode = st.sidebar.selectbox("モード", ["essence", "curriculum", "topic"], index=0)
skip_research = st.sidebar.checkbox("リサーチをスキップ（高速）", value=True)
skip_eval = st.sidebar.checkbox("品質評価をスキップ", value=False)

st.sidebar.markdown("---")
st.sidebar.markdown("**Ollamaモデル設定**")
reader_model = st.sidebar.text_input("Reader model", value="llama3.2:latest")
dramaturg_model = st.sidebar.text_input("Dramaturg model", value="qwen3.5:latest")

# ── Main area ────────────────────────────────────────────────────────────────
st.title("📚 Project Cogito")

tab_run, tab_results, tab_history = st.tabs(["▶️ 実行", "📄 結果", "📁 履歴"])

# ── Tab: Run ─────────────────────────────────────────────────────────────────
with tab_run:
    st.subheader(f"書籍: {selected_book}" if selected_book else "書籍を選択してください")

    col1, col2 = st.columns([3, 1])
    with col1:
        run_button = st.button("🚀 パイプライン実行", type="primary", disabled=not selected_book)
    with col2:
        st.caption(f"モード: {mode} | リサーチ: {'OFF' if skip_research else 'ON'}")

    if run_button and selected_book:
        cmd = [
            sys.executable, str(BOOK_RESEARCH_DIR / "main.py"),
            "--book", selected_book,
            "--mode", mode,
            "--skip-translate",
            "--skip-audio",
            "--reader-model", reader_model,
            "--dramaturg-model", dramaturg_model,
        ]
        if skip_research:
            cmd.append("--skip-research")
        if skip_eval:
            cmd.append("--skip-eval")

        import os
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "http://host.docker.internal:11434"
        env["PYTHONPATH"] = f"{PYPACKAGES}:{env.get('PYTHONPATH','')}"

        progress_placeholder = st.empty()
        log_placeholder = st.expander("📋 実行ログ", expanded=True)

        with log_placeholder:
            log_text = st.empty()
            lines_collected = []

            proc = subprocess.Popen(
                cmd, cwd=str(BOOK_RESEARCH_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env
            )

            for line in proc.stdout:
                line = line.rstrip()
                lines_collected.append(line)
                log_text.code("\n".join(lines_collected[-30:]))

                if line.startswith("[") and "/" in line and "]" in line:
                    try:
                        bracket_end = line.index("]")
                        rest = line[bracket_end + 2:]
                        progress_placeholder.info(f"⚙️ {rest}")
                    except Exception:
                        pass

                time.sleep(0.01)

            proc.wait()

        if proc.returncode == 0:
            progress_placeholder.success("✅ パイプライン完了！")
            st.balloons()
        else:
            progress_placeholder.error(f"❌ エラー (exit {proc.returncode})")

# ── Tab: Results ─────────────────────────────────────────────────────────────
with tab_results:
    run_dirs = sorted(DATA_DIR.glob("run_*"), reverse=True)
    if not run_dirs:
        st.info("まだ実行結果がありません")
    else:
        selected_run = st.selectbox(
            "実行を選択",
            [d.name for d in run_dirs],
            index=0
        )
        if selected_run:
            run_dir = DATA_DIR / selected_run

            col1, col2, col3 = st.columns(3)

            # Script
            scripts_path = run_dir / "05_scripts.md"
            if scripts_path.exists():
                with col1:
                    st.subheader("🎙️ スクリプト")
                    st.markdown(scripts_path.read_text(encoding="utf-8"))

            # Concept graph
            graph_path = run_dir / "03_concept_graph.md"
            if graph_path.exists():
                with col2:
                    st.subheader("🕸️ コンセプトグラフ")
                    st.markdown(graph_path.read_text(encoding="utf-8")[:3000])

            # Syllabus
            syllabus_path = run_dir / "04_syllabus.md"
            if syllabus_path.exists():
                with col3:
                    st.subheader("📋 シラバス")
                    st.markdown(syllabus_path.read_text(encoding="utf-8"))

            # Eval scores
            eval_scores_path = run_dir / "eval_scores.json"
            if eval_scores_path.exists():
                st.subheader("⭐ 品質スコア")
                scores = json.loads(eval_scores_path.read_text())
                for i, score in enumerate(scores):
                    with st.expander(f"Episode {i+1} — overall: {score.get('overall', '?')}/5"):
                        st.json(score)

# ── Tab: History ─────────────────────────────────────────────────────────────
with tab_history:
    st.subheader("📁 実行履歴")
    run_dirs = sorted(DATA_DIR.glob("run_*"), reverse=True)

    if not run_dirs:
        st.info("履歴がありません")
    else:
        for run_dir in run_dirs[:20]:
            has_script = (run_dir / "05_scripts.md").exists()
            has_graph = (run_dir / "03_concept_graph.md").exists()
            icon = "✅" if has_script else "⏳" if has_graph else "❌"
            st.text(f"{icon} {run_dir.name}")
