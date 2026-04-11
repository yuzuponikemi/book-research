# Project Cogito (book-research) — 現在の状況

最終更新: 2026-03-25

## 状態

🟡 一時停止（開発中・未完のフェーズあり）

## プロジェクト概要

書籍 or Webリサーチ → 概念グラフ → ポッドキャスト台本 → 音声合成（VOICEVOX）のLangGraphパイプライン。

## 直近の作業

- [2026-03-22] `apply.sh` 経由でのパッチ適用（usage-tracking）、本プロジェクトには影響なし
- （その前の作業履歴は未記録 — 今後から記録開始）

## 現在の状態詳細

- パイプラインの基本フローは実装済み（Ingestor → Analyst → Producer → Audio → Translator）
- LangGraph + SQLite チェックポインティングによる `--resume` 機能あり
- Webリサーチモード（Route B）実装済み
- テスト (`tests/`) あり

## 次のステップ（idea.md より優先度高）

- [ ] Human-in-the-Loop の実装（LangGraph `interrupt_before`/`interrupt_after`）
- [ ] Self-Critique ループ（台本生成後にLLM自身が評価→再生成）
- [ ] コンセプトグラフの可視化（Mermaid / D3.js）

## 現在の課題・メモ

- Ollama モデルが重いため Apple Silicon 上での逐次処理が必須
- PDF/EPUB 対応は未実装（現状はGutenbergテキスト・Markdown・URLのみ）
- 詳細な拡張アイデアは `idea.md` に記載（優先度付き）
