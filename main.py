"""CLI entry point for Project Cogito.

Runs the pipeline step-by-step, saving human-readable intermediate outputs
after each stage so you can review and debug the process.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from src.book_config import load_book_config
from src.logger import flush_log, make_run_id
from src.reader.ingestion import ingest
from src.reader.analyst import analyze_chunks
from src.reader.synthesizer import synthesize
from src.researcher.researcher import research, format_research_context
from src.critic.critic import critique, format_critique_report
from src.director.enricher import enrich, format_enrichment_report
from src.researcher.reading_material import generate_reading_material
from src.director.planner import plan
from src.dramaturg.scriptwriter import write_scripts
from src.translator import translate_intermediate_outputs


CONFIG_DIR = Path(__file__).parent / "config"
DATA_DIR = Path(__file__).parent / "data"


def load_persona_config(preset_name: str) -> dict:
    """Load a persona preset from config/personas.yaml."""
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


def save_intermediate(run_dir: Path, stage: str, data: dict) -> Path:
    """Save intermediate output as pretty-printed JSON."""
    path = run_dir / f"{stage}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return path


def save_readable(run_dir: Path, filename: str, text: str) -> Path:
    """Save a human-readable text file."""
    path = run_dir / filename
    path.write_text(text, encoding="utf-8")
    return path


def format_chunks_report(chunks: list[str]) -> str:
    """Create a human-readable report of the text chunks."""
    lines = ["# Ingestion Report", ""]
    lines.append(f"Total chunks: {len(chunks)}")
    lines.append("")
    for i, chunk in enumerate(chunks):
        first_line = chunk.strip().split("\n")[0]
        lines.append(f"## Chunk {i+1}: {first_line}")
        lines.append(f"Length: {len(chunk)} characters, ~{len(chunk.split())} words")
        # Show first 300 chars as preview
        preview = chunk[:300].replace("\n", "\n> ")
        lines.append(f"\n> {preview}...")
        lines.append("")
    return "\n".join(lines)


def format_analysis_report(analyses: list[dict]) -> str:
    """Create a human-readable report of per-chunk analyses."""
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
                    lines.append(f"  > \"{q[:100]}\"")
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
                    lines.append(f"  > \"{rs['original_quote'][:100]}\"")
            lines.append("")

        logic = analysis.get("logic_flow", "")
        if logic:
            lines.append(f"### Logic Flow")
            lines.append(logic[:500])
            lines.append("")

        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def format_concept_graph_report(cg: dict) -> str:
    """Create a human-readable concept graph report."""
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
                lines.append(f"> \"{q}\"")
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
    """Create a human-readable syllabus report."""
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
        concept_ids = ep.get('concept_ids', [])
        if isinstance(concept_ids, list):
            lines.append(f"**Concepts:** {', '.join(str(c) for c in concept_ids)}")
        lines.append(f"**Aporias:** {', '.join(str(a) for a in ep.get('aporia_ids', []) if isinstance(ep.get('aporia_ids'), list))}")
        lines.append(f"**Cognitive Bridge:** {ep.get('cognitive_bridge', '')}")
        lines.append(f"**Cliffhanger:** {ep.get('cliffhanger', '')}")
        lines.append("")

    return "\n".join(lines)


def format_scripts_report(scripts: list[dict]) -> str:
    """Create a human-readable scripts report."""
    lines = ["# Generated Scripts", ""]

    for script in scripts:
        if not isinstance(script, dict):
            lines.append(f"(skipped non-dict script)")
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


def main():
    parser = argparse.ArgumentParser(
        description="Project Cogito: Philosophical text -> podcast scripts"
    )
    parser.add_argument(
        "--book",
        default="descartes_discourse",
        help="Book config name from config/books/ (default: descartes_discourse)",
    )
    parser.add_argument(
        "--mode",
        choices=["essence", "curriculum", "topic"],
        default="essence",
        help="Episode planning mode (default: essence)",
    )
    parser.add_argument(
        "--persona",
        default="descartes_default",
        help="Persona preset name from config/personas.yaml (default: descartes_default)",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Topic to focus on (required for topic mode)",
    )
    parser.add_argument(
        "--reader-model",
        default="llama3",
        help="Ollama model for Reader/Director layers (default: llama3)",
    )
    parser.add_argument(
        "--dramaturg-model",
        default="qwen3-next",
        help="Ollama model for Dramaturg layer (default: qwen3-next)",
    )
    parser.add_argument(
        "--translator-model",
        default="translategemma:12b",
        help="Ollama model for Japanese translation (default: translategemma:12b)",
    )
    parser.add_argument(
        "--skip-translate",
        action="store_true",
        help="Skip the translation step",
    )
    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Skip research/critique/enrichment stages (use original pipeline only)",
    )
    args = parser.parse_args()

    if args.mode == "topic" and not args.topic:
        parser.error("--topic is required when using topic mode")

    # Load book configuration
    book_config = load_book_config(args.book)
    book = book_config["book"]
    book_title = book["title"]

    persona_config = load_persona_config(args.persona)
    run_id = make_run_id()

    # Create per-run output directory
    run_dir = DATA_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Count total stages
    base_stages = 5  # ingest, analyze, synthesize, plan, script
    research_stages = 0 if args.skip_research else 4  # research, critique, enrich, reading material
    translate_stages = 0 if args.skip_translate else 1
    total_stages = base_stages + research_stages + translate_stages
    current_stage = 0

    print("=" * 60)
    print("  Project Cogito")
    print("=" * 60)
    print(f"  Run ID       : {run_id}")
    print(f"  Book         : {book_title} ({book.get('author', '')})")
    print(f"  Mode         : {args.mode}")
    print(f"  Persona      : {args.persona}")
    print(f"  Reader model : {args.reader_model}")
    print(f"  Dramaturg    : {args.dramaturg_model}")
    if not args.skip_translate:
        print(f"  Translator   : {args.translator_model}")
    print(f"  Research     : {'skip' if args.skip_research else 'enabled'}")
    if args.topic:
        print(f"  Topic        : {args.topic}")
    print(f"  Output dir   : {run_dir}")
    print("=" * 60)
    print()

    # Build work_description for translator
    pf = book_config.get("prompt_fragments", {})
    work_description = pf.get(
        "work_description",
        f'{book.get("author", "the author")}\'s "{book_title}"'
    )

    # Shared state that accumulates through the pipeline
    state = {
        "book_title": book_title,
        "book_config": book_config,
        "raw_chunks": [],
        "chunk_analyses": [],
        "concept_graph": {},
        "research_context": {},
        "critique_report": {},
        "enrichment": {},
        "mode": args.mode,
        "topic": args.topic,
        "persona_config": persona_config,
        "syllabus": {},
        "scripts": [],
        "thinking_log": [],
        "reader_model": args.reader_model,
        "dramaturg_model": args.dramaturg_model,
    }

    # ── Stage 1: Ingest ─────────────────────────────────────────
    current_stage += 1
    print(f"[{current_stage}/{total_stages}] Ingestion: downloading and chunking text...")
    t0 = time.time()

    result = ingest(state)
    state.update(result)

    elapsed = time.time() - t0
    n_chunks = len(state["raw_chunks"])
    print(f"      -> {n_chunks} chunks in {elapsed:.1f}s")

    # Save intermediate
    save_intermediate(run_dir, "01_chunks", {
        "chunk_count": n_chunks,
        "chunks": [
            {"index": i, "first_line": c.split("\n")[0], "length": len(c)}
            for i, c in enumerate(state["raw_chunks"])
        ],
    })
    p = save_readable(run_dir, "01_chunks.md", format_chunks_report(state["raw_chunks"]))
    print(f"      Saved: {p}")
    print()

    # ── Stage 2: Analyze chunks ─────────────────────────────────
    current_stage += 1
    print(f"[{current_stage}/{total_stages}] Analysis: extracting concepts from {n_chunks} chunks (model: {args.reader_model})...")
    print(f"      This will make {n_chunks} LLM calls — may take a while.")
    t0 = time.time()

    result = analyze_chunks(state)
    state.update(result)

    elapsed = time.time() - t0
    total_concepts = sum(len(a.get("concepts", [])) for a in state["chunk_analyses"])
    total_aporias = sum(len(a.get("aporias", [])) for a in state["chunk_analyses"])
    total_arguments = sum(len(a.get("arguments", [])) for a in state["chunk_analyses"])
    print(f"      -> {total_concepts} concepts, {total_aporias} aporias, "
          f"{total_arguments} arguments across all chunks ({elapsed:.1f}s)")

    save_intermediate(run_dir, "02_chunk_analyses", state["chunk_analyses"])
    p = save_readable(run_dir, "02_chunk_analyses.md", format_analysis_report(state["chunk_analyses"]))
    print(f"      Saved: {p}")
    print()

    # ── Stage 3: Synthesize ─────────────────────────────────────
    current_stage += 1
    print(f"[{current_stage}/{total_stages}] Synthesis: merging chunk analyses into unified concept graph...")
    t0 = time.time()

    result = synthesize(state)
    state.update(result)

    elapsed = time.time() - t0
    cg = state["concept_graph"]
    print(f"      -> {len(cg.get('concepts', []))} concepts, "
          f"{len(cg.get('relations', []))} relations, "
          f"{len(cg.get('aporias', []))} aporias ({elapsed:.1f}s)")
    if cg.get("core_frustration"):
        print(f"      Core frustration: {cg['core_frustration'][:100]}")

    save_intermediate(run_dir, "03_concept_graph", cg)
    p = save_readable(run_dir, "03_concept_graph.md", format_concept_graph_report(cg))
    print(f"      Saved: {p}")
    print()

    # ── Stage 3b: Research (optional) ────────────────────────────
    if not args.skip_research:
        current_stage += 1
        print(f"[{current_stage}/{total_stages}] Research: gathering web search results and reference materials...")
        t0 = time.time()

        result = research(state)
        state.update(result)

        elapsed = time.time() - t0
        rc = state["research_context"]
        n_sources = len(rc.get("web_sources", []))
        n_refs = len(rc.get("reference_files", []))
        print(f"      -> {n_sources} web sources, {n_refs} reference files ({elapsed:.1f}s)")

        save_intermediate(run_dir, "03b_research_context", rc)
        p = save_readable(run_dir, "03b_research_context.md", format_research_context(rc))
        print(f"      Saved: {p}")
        print()

        # ── Stage 3c: Critique ───────────────────────────────────
        current_stage += 1
        print(f"[{current_stage}/{total_stages}] Critique: generating critical perspectives...")
        t0 = time.time()

        result = critique(state)
        state.update(result)

        elapsed = time.time() - t0
        cr = state["critique_report"]
        n_critiques = len(cr.get("critiques", []))
        n_debates = len(cr.get("overarching_debates", []))
        print(f"      -> {n_critiques} concept critiques, {n_debates} overarching debates ({elapsed:.1f}s)")

        save_intermediate(run_dir, "03c_critique_report", cr)
        p = save_readable(run_dir, "03c_critique_report.md", format_critique_report(cr))
        print(f"      Saved: {p}")
        print()

        # ── Stage 3d: Enrich ─────────────────────────────────────
        current_stage += 1
        print(f"[{current_stage}/{total_stages}] Enrichment: creating integrated context summaries...")
        t0 = time.time()

        result = enrich(state)
        state.update(result)

        elapsed = time.time() - t0
        enrichment = state["enrichment"]
        en_len = len(enrichment.get("enrichment_summary", ""))
        ja_len = len(enrichment.get("enrichment_summary_ja", ""))
        print(f"      -> EN summary: {en_len} chars, JA summary: {ja_len} chars ({elapsed:.1f}s)")

        save_intermediate(run_dir, "03d_enriched_context", enrichment)
        p = save_readable(run_dir, "03d_enriched_context.md", format_enrichment_report(enrichment))
        print(f"      Saved: {p}")
        print()

        # ── Stage 3e: Reading Material ──────────────────────────────
        current_stage += 1
        print(f"[{current_stage}/{total_stages}] Reading Material: generating comprehensive study guide...")
        t0 = time.time()

        result = generate_reading_material(state)
        state.update(result)

        elapsed = time.time() - t0
        rm_text = state.get("reading_material", "")
        print(f"      -> {len(rm_text)} chars ({elapsed:.1f}s)")

        p = save_readable(run_dir, "03e_reading_material.md", rm_text)
        print(f"      Saved: {p}")
        print()

    # ── Stage 4: Plan ───────────────────────────────────────────
    current_stage += 1
    print(f"[{current_stage}/{total_stages}] Planning: generating syllabus ({args.mode} mode)...")
    t0 = time.time()

    result = plan(state)
    state.update(result)

    elapsed = time.time() - t0
    syllabus = state["syllabus"]
    episodes = syllabus.get("episodes", [])
    n_eps = len(episodes)
    print(f"      -> {n_eps} episode(s) ({elapsed:.1f}s)")
    for ep in episodes:
        if isinstance(ep, dict):
            print(f"         Ep{ep.get('episode_number', '?')}: {ep.get('title', '?')}")
        else:
            print(f"         (unexpected format: {str(ep)[:80]})")

    save_intermediate(run_dir, "04_syllabus", syllabus)
    p = save_readable(run_dir, "04_syllabus.md", format_syllabus_report(syllabus))
    print(f"      Saved: {p}")
    print()

    # ── Stage 5: Write scripts ──────────────────────────────────
    current_stage += 1
    print(f"[{current_stage}/{total_stages}] Scriptwriting: generating dialogue (model: {args.dramaturg_model})...")
    print(f"      Writing {n_eps} episode script(s) with persona '{args.persona}'...")
    t0 = time.time()

    result = write_scripts(state)
    state.update(result)

    elapsed = time.time() - t0
    scripts = state["scripts"]
    total_lines = sum(len(s.get("dialogue", [])) for s in scripts)
    print(f"      -> {len(scripts)} script(s), {total_lines} total dialogue lines ({elapsed:.1f}s)")

    save_intermediate(run_dir, "05_scripts", scripts)
    p = save_readable(run_dir, "05_scripts.md", format_scripts_report(scripts))
    print(f"      Saved: {p}")
    print()

    # ── Stage 6: Translate intermediate outputs to Japanese ─────
    if not args.skip_translate:
        current_stage += 1
        print(f"[{current_stage}/{total_stages}] Translation: converting intermediate outputs to Japanese (model: {args.translator_model})...")
        t0 = time.time()

        translated_files = translate_intermediate_outputs(
            run_dir=run_dir,
            model=args.translator_model,
            work_description=work_description,
        )

        elapsed = time.time() - t0
        print(f"      -> {len(translated_files)} file(s) translated ({elapsed:.1f}s)")
        print()

    # ── Flush thinking log ──────────────────────────────────────
    log_path = flush_log(
        run_id=run_id,
        book_title=book_title,
        mode=args.mode,
        steps=state.get("thinking_log", []),
        concept_graph=state.get("concept_graph"),
        syllabus=state.get("syllabus"),
    )

    # ── Summary ─────────────────────────────────────────────────
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
    if not args.skip_translate:
        print(f"    *_ja.md                   - Japanese translations")
    print(f"    *.json                    - Machine-readable versions")
    print()
    print(f"  Thinking log: {log_path}")
    print(f"    Contains full prompt/response pairs for every LLM call.")
    print(f"    Use this to trace how each concept was extracted.")
    print()


if __name__ == "__main__":
    main()
