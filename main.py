"""CLI entry point for Project Cogito.

Runs the LangGraph pipeline with SQLite checkpointing, saving human-readable
intermediate outputs after each stage.  Supports --resume and --from-node for
mid-pipeline restarts.
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import yaml

from langgraph.checkpoint.sqlite import SqliteSaver

from src.book_config import load_book_config
from src.graph import build_graph
from src.logger import flush_log, make_run_id
from src.audio.synthesizer import format_audio_report
from src.researcher.researcher import format_research_context
from src.critic.critic import format_critique_report
from src.director.enricher import format_enrichment_report


CONFIG_DIR = Path(__file__).parent / "config"
DATA_DIR = Path(__file__).parent / "data"

# Thread ID used for LangGraph checkpointer (one graph execution per run).
THREAD_ID = "cogito"


# ---------------------------------------------------------------------------
# Format helpers (produce .md content from node output)
# ---------------------------------------------------------------------------

def format_chunks_report(chunks: list[str]) -> str:
    lines = ["# Ingestion Report", ""]
    lines.append(f"Total chunks: {len(chunks)}")
    lines.append("")
    for i, chunk in enumerate(chunks):
        first_line = chunk.strip().split("\n")[0]
        lines.append(f"## Chunk {i+1}: {first_line}")
        lines.append(f"Length: {len(chunk)} characters, ~{len(chunk.split())} words")
        preview = chunk[:300].replace("\n", "\n> ")
        lines.append(f"\n> {preview}...")
        lines.append("")
    return "\n".join(lines)


def format_analysis_report(analyses: list[dict]) -> str:
    lines = ["# Chunk Analysis Report", ""]
    for i, analysis in enumerate(analyses):
        concepts = analysis.get("concepts", [])
        aporias = analysis.get("aporias", [])
        relations = analysis.get("relations", [])
        arguments = analysis.get("arguments", [])
        rhetorical = analysis.get("rhetorical_strategies", [])
        lines.append(f"## Chunk {i+1}")
        lines.append(
            f"Concepts: {len(concepts)} | Aporias: {len(aporias)} | "
            f"Relations: {len(relations)} | Arguments: {len(arguments)} | "
            f"Rhetorical: {len(rhetorical)}"
        )
        lines.append("")

        if concepts:
            lines.append("### Concepts")
            for c in concepts:
                lines.append(f"- **{c.get('name', '?')}** (`{c.get('id', '?')}`)")
                lines.append(f"  {c.get('description', '')[:120]}")
                for q in c.get("original_quotes", [])[:2]:
                    lines.append(f'  > "{q[:100]}"')
            lines.append("")

        if aporias:
            lines.append("### Aporias")
            for a in aporias:
                lines.append(f"- **{a.get('question', '?')}**")
                lines.append(f"  Context: {a.get('context', '')[:120]}")
            lines.append("")

        if relations:
            lines.append("### Relations")
            for r in relations:
                lines.append(f"- {r.get('source', '?')} --[{r.get('relation_type', '?')}]--> {r.get('target', '?')}")
                lines.append(f"  {r.get('evidence', '')[:100]}")
            lines.append("")

        if arguments:
            lines.append("### Argument Structures")
            for arg in arguments:
                lines.append(f"- **{arg.get('id', '?')}** ({arg.get('argument_type', '?')})")
                for p in arg.get("premises", []):
                    lines.append(f"  - Premise: {p[:100]}")
                lines.append(f"  - Conclusion: {arg.get('conclusion', '')[:100]}")
            lines.append("")

        if rhetorical:
            lines.append("### Rhetorical Strategies")
            for rs in rhetorical:
                lines.append(f"- **{rs.get('strategy_type', '?')}** (`{rs.get('id', '?')}`)")
                lines.append(f"  {rs.get('description', '')[:120]}")
                if rs.get("original_quote"):
                    lines.append(f'  > "{rs["original_quote"][:100]}"')
            lines.append("")

        logic = analysis.get("logic_flow", "")
        if logic:
            lines.append("### Logic Flow")
            lines.append(logic[:500])
            lines.append("")

        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def format_concept_graph_report(cg: dict) -> str:
    lines = ["# Unified Concept Graph", ""]
    concepts = cg.get("concepts", [])
    relations = cg.get("relations", [])
    aporias = cg.get("aporias", [])

    lines.append(f"**{len(concepts)} concepts, {len(relations)} relations, {len(aporias)} aporias**")
    lines.append("")

    if cg.get("core_frustration"):
        lines.append("## Core Frustration")
        lines.append(cg["core_frustration"])
        lines.append("")

    if cg.get("logic_flow"):
        lines.append("## Logic Flow")
        lines.append(cg["logic_flow"])
        lines.append("")

    if concepts:
        lines.append("## Concepts")
        for c in concepts:
            lines.append(f"### {c.get('name', '?')} (`{c.get('id', '?')}`) [from {c.get('source_chunk', '?')}]")
            lines.append(c.get("description", ""))
            for q in c.get("original_quotes", []):
                lines.append(f'> "{q}"')
            lines.append("")

    if relations:
        lines.append("## Relations")
        for r in relations:
            arrow = {"depends_on": "-->", "contradicts": "<->", "evolves_into": "==>"}
            sym = arrow.get(r.get("relation_type", ""), "---")
            lines.append(f"- `{r.get('source', '?')}` {sym} `{r.get('target', '?')}` ({r.get('relation_type', '?')})")
            lines.append(f"  {r.get('evidence', '')}")
        lines.append("")

    if aporias:
        lines.append("## Aporias (Unresolved Tensions)")
        for a in aporias:
            lines.append(f"### {a.get('question', '?')}")
            lines.append(f"Context: {a.get('context', '')}")
            lines.append(f"Related concepts: {', '.join(a.get('related_concepts', []))}")
            lines.append("")

    return "\n".join(lines)


def format_syllabus_report(syllabus: dict) -> str:
    lines = ["# Syllabus", ""]
    lines.append(f"Mode: {syllabus.get('mode', '?')}")
    lines.append(f"Meta-narrative: {syllabus.get('meta_narrative', '')}")
    lines.append("")

    for ep in syllabus.get("episodes", []):
        if not isinstance(ep, dict):
            lines.append(f"(skipped non-dict episode: {str(ep)[:80]})")
            continue
        lines.append(f"## Episode {ep.get('episode_number', '?')}: {ep.get('title', '?')}")
        lines.append(f"**Theme:** {ep.get('theme', '')}")
        concept_ids = ep.get("concept_ids", [])
        if isinstance(concept_ids, list):
            lines.append(f"**Concepts:** {', '.join(str(c) for c in concept_ids)}")
        lines.append(f"**Aporias:** {', '.join(str(a) for a in ep.get('aporia_ids', []) if isinstance(ep.get('aporia_ids'), list))}")
        lines.append(f"**Cognitive Bridge:** {ep.get('cognitive_bridge', '')}")
        lines.append(f"**Cliffhanger:** {ep.get('cliffhanger', '')}")
        lines.append("")

    return "\n".join(lines)


def format_scripts_report(scripts: list[dict]) -> str:
    lines = ["# Generated Scripts", ""]
    for script in scripts:
        if not isinstance(script, dict):
            lines.append("(skipped non-dict script)")
            continue
        lines.append(f"## Episode {script.get('episode_number', '?')}: {script.get('title', '?')}")
        lines.append("")

        bridge = script.get("opening_bridge", "")
        if bridge:
            lines.append(f"*[Opening Bridge]* {bridge}")
            lines.append("")

        lines.append("### Dialogue")
        lines.append("")
        for dl in script.get("dialogue", []):
            if isinstance(dl, dict):
                lines.append(f"**{dl.get('speaker', '?')}:** {dl.get('line', '')}")
            else:
                lines.append(f"**?:** {dl}")
            lines.append("")

        hook = script.get("closing_hook", "")
        if hook:
            lines.append(f"*[Closing Hook]* {hook}")
            lines.append("")

        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node metadata: label, file prefix, save callback
# ---------------------------------------------------------------------------

def _save(run_dir: Path, prefix: str, data, fmt_fn=None):
    """Save JSON + optional .md for a node's output."""
    json_path = run_dir / f"{prefix}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    if fmt_fn:
        md_path = run_dir / f"{prefix}.md"
        md_path.write_text(fmt_fn(data), encoding="utf-8")
        return md_path
    return json_path


# Each entry:  (label, file_prefix, state_key, format_fn, summary_fn)
# summary_fn(state_snapshot) -> str  (one-line summary printed after the node)
NODE_META: dict[str, tuple] = {
    "ingest": (
        "Ingestion",
        "01_chunks",
        "raw_chunks",
        lambda data: format_chunks_report(data) if isinstance(data, list) else "",
        lambda s: f"{len(s.get('raw_chunks', []))} chunks",
    ),
    "analyze_chunks": (
        "Chunk Analysis",
        "02_chunk_analyses",
        "chunk_analyses",
        format_analysis_report,
        lambda s: (
            f"{sum(len(a.get('concepts',[])) for a in s.get('chunk_analyses',[]))} concepts, "
            f"{sum(len(a.get('aporias',[])) for a in s.get('chunk_analyses',[]))} aporias"
        ),
    ),
    "synthesize": (
        "Synthesis",
        "03_concept_graph",
        "concept_graph",
        format_concept_graph_report,
        lambda s: (
            f"{len(s.get('concept_graph',{}).get('concepts',[]))} concepts, "
            f"{len(s.get('concept_graph',{}).get('relations',[]))} relations"
        ),
    ),
    "research": (
        "Research",
        "03b_research_context",
        "research_context",
        format_research_context,
        lambda s: (
            f"{len(s.get('research_context',{}).get('web_sources',[]))} web sources, "
            f"{len(s.get('research_context',{}).get('reference_files',[]))} refs"
        ),
    ),
    "critique": (
        "Critique",
        "03c_critique_report",
        "critique_report",
        format_critique_report,
        lambda s: (
            f"{len(s.get('critique_report',{}).get('critiques',[]))} critiques"
        ),
    ),
    "enrich": (
        "Enrichment",
        "03d_enriched_context",
        "enrichment",
        format_enrichment_report,
        lambda s: (
            f"EN {len(s.get('enrichment',{}).get('enrichment_summary',''))} chars, "
            f"JA {len(s.get('enrichment',{}).get('enrichment_summary_ja',''))} chars"
        ),
    ),
    "generate_reading_material": (
        "Reading Material",
        "03e_reading_material",
        "reading_material",
        lambda data: data if isinstance(data, str) else "",
        lambda s: f"{len(s.get('reading_material',''))} chars",
    ),
    "plan": (
        "Planning",
        "04_syllabus",
        "syllabus",
        format_syllabus_report,
        lambda s: f"{len(s.get('syllabus',{}).get('episodes',[]))} episodes",
    ),
    "write_scripts": (
        "Scriptwriting",
        "05_scripts",
        "scripts",
        format_scripts_report,
        lambda s: (
            f"{len(s.get('scripts',[]))} scripts, "
            f"{sum(len(sc.get('dialogue',[])) for sc in s.get('scripts',[]))} lines"
        ),
    ),
    "synthesize_audio": (
        "Audio Synthesis",
        "06_audio",
        "audio_metadata",
        format_audio_report,
        lambda s: (
            f"{len(s.get('audio_metadata',[]))} episodes"
            if s.get("audio_metadata") else "skipped"
        ),
    ),
    "check_translate": (
        "Check Translate",
        None,
        None,
        None,
        lambda s: "",
    ),
    "translate": (
        "Translation",
        None,  # translate_node writes files directly
        None,
        None,
        lambda s: "done",
    ),
}


# ---------------------------------------------------------------------------
# Node ordering helpers (for --from-node)
# ---------------------------------------------------------------------------

# Canonical node order (all nodes in the graph).
ALL_NODES_ORDERED = [
    "ingest",
    "analyze_chunks",
    "synthesize",
    "research",
    "critique",
    "enrich",
    "generate_reading_material",
    "plan",
    "write_scripts",
    "synthesize_audio",
    "check_translate",
    "translate",
]


def _build_active_sequence(state: dict) -> list[str]:
    """Return the list of nodes that were/will actually execute given skip flags."""
    skip_research = state.get("skip_research", False)
    skip_audio = state.get("skip_audio", False)
    skip_translate = state.get("skip_translate", False)

    seq = ["ingest", "analyze_chunks", "synthesize"]
    if not skip_research:
        seq += ["research", "critique", "enrich", "generate_reading_material"]
    seq.append("plan")
    seq.append("write_scripts")
    if not skip_audio:
        seq.append("synthesize_audio")
    seq.append("check_translate")
    if not skip_translate:
        seq.append("translate")
    return seq


def _predecessor(node: str, active_seq: list[str]) -> str | None:
    """Return the node just before *node* in the active sequence."""
    try:
        idx = active_seq.index(node)
    except ValueError:
        return None
    return active_seq[idx - 1] if idx > 0 else None


# ---------------------------------------------------------------------------
# Persona loader
# ---------------------------------------------------------------------------

def load_persona_config(preset_name: str) -> dict:
    personas_path = CONFIG_DIR / "personas.yaml"
    with open(personas_path) as f:
        config = yaml.safe_load(f)

    presets = config.get("presets", {})
    if preset_name not in presets:
        available = ", ".join(presets.keys())
        print(f"Error: Unknown persona preset '{preset_name}'")
        print(f"Available presets: {available}")
        sys.exit(1)

    return presets[preset_name]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Project Cogito: Philosophical text -> podcast scripts"
    )
    parser.add_argument(
        "--book", default="descartes_discourse",
        help="Book config name from config/books/ (default: descartes_discourse)",
    )
    parser.add_argument(
        "--mode", choices=["essence", "curriculum", "topic"], default="essence",
        help="Episode planning mode (default: essence)",
    )
    parser.add_argument(
        "--persona", default="descartes_default",
        help="Persona preset name from config/personas.yaml (default: descartes_default)",
    )
    parser.add_argument("--topic", default=None, help="Topic to focus on (required for topic mode)")
    parser.add_argument(
        "--reader-model", default="llama3",
        help="Ollama model for Reader/Director layers (default: llama3)",
    )
    parser.add_argument(
        "--dramaturg-model", default="qwen3-next",
        help="Ollama model for Dramaturg layer (default: qwen3-next)",
    )
    parser.add_argument(
        "--translator-model", default="translategemma:12b",
        help="Ollama model for Japanese translation (default: translategemma:12b)",
    )
    parser.add_argument("--skip-translate", action="store_true", help="Skip the translation step")
    parser.add_argument("--skip-research", action="store_true", help="Skip research/critique/enrichment stages")
    parser.add_argument("--skip-audio", action="store_true", help="Skip VOICEVOX audio synthesis stage")
    parser.add_argument(
        "--resume", metavar="RUN_ID", default=None,
        help="Resume from a previous run's checkpoint (e.g. run_20250210_153000)",
    )
    parser.add_argument(
        "--from-node", metavar="NODE", default=None,
        help="Re-execute from this node onward (requires --resume)",
    )
    args = parser.parse_args()

    if args.mode == "topic" and not args.topic:
        parser.error("--topic is required when using topic mode")
    if args.from_node and not args.resume:
        parser.error("--from-node requires --resume")
    if args.from_node and args.from_node not in ALL_NODES_ORDERED:
        parser.error(f"Unknown node '{args.from_node}'. "
                     f"Valid nodes: {', '.join(ALL_NODES_ORDERED)}")

    # --- Determine run_id and run_dir ---
    resuming = args.resume is not None
    run_id = args.resume if resuming else make_run_id()
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # --- Load configs ---
    book_config = load_book_config(args.book)
    book = book_config["book"]
    book_title = book["title"]
    persona_config = load_persona_config(args.persona)

    pf = book_config.get("prompt_fragments", {})
    work_description = pf.get(
        "work_description",
        f'{book.get("author", "the author")}\'s "{book_title}"',
    )

    # --- Build checkpointer and graph ---
    db_path = run_dir / "checkpoint.sqlite"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    graph = build_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": THREAD_ID}}

    # --- Initial state (for fresh runs) ---
    initial_state = {
        "book_title": book_title,
        "book_config": book_config,
        "raw_chunks": [],
        "chunk_analyses": [],
        "concept_graph": {},
        "research_context": {},
        "critique_report": {},
        "enrichment": {},
        "reading_material": "",
        "mode": args.mode,
        "topic": args.topic,
        "persona_config": persona_config,
        "syllabus": {},
        "scripts": [],
        "audio_metadata": [],
        "thinking_log": [],
        "reader_model": args.reader_model,
        "dramaturg_model": args.dramaturg_model,
        "translator_model": args.translator_model,
        "work_description": work_description,
        "skip_research": args.skip_research,
        "skip_audio": args.skip_audio,
        "skip_translate": args.skip_translate,
        "run_dir": str(run_dir),
        "run_id": run_id,
    }

    # --- Count expected stages for progress display ---
    base_stages = 5  # ingest, analyze, synthesize, plan, script
    research_stages = 0 if args.skip_research else 4
    audio_stages = 0 if args.skip_audio else 1
    translate_stages = 0 if args.skip_translate else 1
    total_stages = base_stages + research_stages + audio_stages + translate_stages

    # --- Banner ---
    print("=" * 60)
    print("  Project Cogito")
    print("=" * 60)
    print(f"  Run ID       : {run_id}")
    if resuming:
        print(f"  Resuming     : yes{f' (from {args.from_node})' if args.from_node else ''}")
    print(f"  Book         : {book_title} ({book.get('author', '')})")
    print(f"  Mode         : {args.mode}")
    print(f"  Persona      : {args.persona}")
    print(f"  Reader model : {args.reader_model}")
    print(f"  Dramaturg    : {args.dramaturg_model}")
    if not args.skip_translate:
        print(f"  Translator   : {args.translator_model}")
    print(f"  Research     : {'skip' if args.skip_research else 'enabled'}")
    print(f"  Audio        : {'skip' if args.skip_audio else 'VOICEVOX (localhost:50021)'}")
    if args.topic:
        print(f"  Topic        : {args.topic}")
    print(f"  Output dir   : {run_dir}")
    print(f"  Checkpoint   : {db_path}")
    print("=" * 60)
    print()

    # --- Handle --from-node: rewind checkpoint to predecessor ---
    stream_input: dict | None
    if resuming and args.from_node:
        active_seq = _build_active_sequence(initial_state)
        prev = _predecessor(args.from_node, active_seq)
        if prev is None:
            # Re-running from the very first node — pass initial state
            stream_input = initial_state
            print(f"  Restarting from beginning (first node: {args.from_node})")
        else:
            # Patch state with any CLI overrides that might have changed
            overrides = {
                "reader_model": args.reader_model,
                "dramaturg_model": args.dramaturg_model,
                "translator_model": args.translator_model,
                "work_description": work_description,
                "persona_config": persona_config,
                "skip_research": args.skip_research,
                "skip_audio": args.skip_audio,
                "skip_translate": args.skip_translate,
                "run_dir": str(run_dir),
            }
            graph.update_state(config, overrides, as_node=prev)
            stream_input = None
            print(f"  Checkpoint rewound to after '{prev}', resuming from '{args.from_node}'")
        print()
    elif resuming:
        # Plain resume — continue from last checkpoint
        stream_input = None
        print("  Resuming from last checkpoint...")
        print()
    else:
        stream_input = initial_state

    # --- Stream execution ---
    current_stage = 0
    t_node_start = time.time()

    try:
        for event in graph.stream(stream_input, config, stream_mode="updates"):
            elapsed = time.time() - t_node_start

            for node_name, output in event.items():
                meta = NODE_META.get(node_name)
                if meta is None:
                    continue

                label, prefix, state_key, fmt_fn, summary_fn = meta

                # Skip no-op nodes in progress count
                if node_name == "check_translate":
                    t_node_start = time.time()
                    continue

                current_stage += 1
                # Save intermediate files
                if prefix and state_key and output.get(state_key) is not None:
                    data = output[state_key]
                    _save(run_dir, prefix, data, fmt_fn)

                # Special: reading_material is a string, not a dict
                if node_name == "generate_reading_material" and isinstance(output.get("reading_material"), str):
                    md_path = run_dir / f"{prefix}.md"
                    md_path.write_text(output["reading_material"], encoding="utf-8")

                # Build summary from the streamed output merged into a snapshot
                snapshot = dict(initial_state)
                snapshot.update(output)
                summary = summary_fn(snapshot) if summary_fn else ""

                print(f"[{current_stage}/{total_stages}] {label}: {summary} ({elapsed:.1f}s)")

            t_node_start = time.time()

    except KeyboardInterrupt:
        print()
        print("  Interrupted! Progress saved to checkpoint.")
        print(f"  Resume with: python3 main.py --book {args.book} --resume {run_id}")
        conn.close()
        sys.exit(130)

    # --- Flush thinking log ---
    final_state = graph.get_state(config)
    state_values = final_state.values if final_state else initial_state

    log_path = flush_log(
        run_id=run_id,
        book_title=book_title,
        mode=args.mode,
        steps=state_values.get("thinking_log", []),
        concept_graph=state_values.get("concept_graph"),
        syllabus=state_values.get("syllabus"),
    )

    conn.close()

    # --- Summary ---
    print()
    print("=" * 60)
    print("  Pipeline complete!")
    print("=" * 60)
    print()
    print(f"  Output directory: {run_dir}/")
    print(f"    01_chunks.md              - Raw text chunks")
    print(f"    02_chunk_analyses.md      - Per-chunk concept extraction")
    print(f"    03_concept_graph.md       - Unified concept graph")
    if not args.skip_research:
        print(f"    03b_research_context.md   - Web search + reference materials")
        print(f"    03c_critique_report.md    - Critical perspectives")
        print(f"    03d_enriched_context.md   - Integrated context narrative")
        print(f"    03e_reading_material.md   - Comprehensive study guide")
    print(f"    04_syllabus.md            - Episode plan")
    print(f"    05_scripts.md             - Final dialogue scripts")
    if not args.skip_audio:
        print(f"    06_audio/                 - MP3 audio files (VOICEVOX)")
    if not args.skip_translate:
        print(f"    *_ja.md                   - Japanese translations")
    print(f"    *.json                    - Machine-readable versions")
    print(f"    checkpoint.sqlite         - LangGraph checkpoint (for --resume)")
    print()
    print(f"  Thinking log: {log_path}")
    print(f"  Resume: python3 main.py --book {args.book} --resume {run_id}")
    print()


if __name__ == "__main__":
    main()
