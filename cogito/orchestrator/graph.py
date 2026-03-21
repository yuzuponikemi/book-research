"""LangGraph wiring: cogito services as pipeline nodes.

Topology:
    route
      → (if source==web) → web_research → produce
      → (if source==book) → ingest → analyze_chunks → synthesize_graph
          → (if not skip_research) → web_research → produce
          → (if skip_research) → produce
    produce
      → (if not skip_audio) → synthesize_audio → check_translate
      → (if skip_audio) → check_translate
    check_translate
      → (if not skip_translate) → translate → END
      → (if skip_translate) → END
"""

from __future__ import annotations

import json
from pathlib import Path

from langgraph.graph import StateGraph, END

from cogito.orchestrator.state import CogitoState
from cogito.utils import event_log


# ── Node implementations ───────────────────────────────────────────────────────

def node_ingest(state: CogitoState) -> dict:
    event_log.step("orchestrator/graph", "→ node: ingest")
    from cogito.config.book_config import load_book_config
    from cogito.services.ingestor.adapters.book import ingest_from_book_config

    book_config = load_book_config(state["book_config"]["_name"])
    chunks_v1, _log = ingest_from_book_config(book_config)

    run_dir = Path(state["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = run_dir / "01_chunks.json"
    chunks_path.write_text(chunks_v1.model_dump_json(indent=2), encoding="utf-8")

    chunk_tuples = [(c.id, c.text) for c in chunks_v1.chunks]
    print(f"  → {len(chunk_tuples)} chunks ingested", flush=True)

    steps = list(state.get("thinking_log", []))
    steps.append({"layer": "ingestor", "node": "ingest", "action": "ingest",
                  "reasoning": f"Ingested {len(chunk_tuples)} chunks"})
    return {"chunk_tuples": chunk_tuples, "thinking_log": steps}


def node_analyze_chunks(state: CogitoState) -> dict:
    event_log.step("orchestrator/graph", "→ node: analyze_chunks")
    from cogito.services.analyst.extractor import extract_all_chunks

    key_terms = state.get("book_config", {}).get("context", {}).get("key_terms") or None
    analyses, _log = extract_all_chunks(
        state["chunk_tuples"],
        model=state["reader_model"],
        key_terms=key_terms,
    )
    run_dir = Path(state["run_dir"])
    (run_dir / "02_chunk_analyses.json").write_text(
        json.dumps(analyses, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    steps = list(state.get("thinking_log", []))
    steps.append({"layer": "analyst", "node": "analyze_chunks", "action": "extract_all",
                  "reasoning": f"Extracted concepts from {len(analyses)} chunks"})
    return {"chunk_analyses": analyses, "thinking_log": steps}


def node_synthesize_graph(state: CogitoState) -> dict:
    event_log.step("orchestrator/graph", "→ node: synthesize_graph")
    from cogito.services.analyst.synthesizer import synthesize_concept_graph

    work_description = state.get("work_description", state.get("book_title", "unknown"))
    graph, _log = synthesize_concept_graph(
        state["chunk_analyses"],
        work_description=work_description,
        subject=work_description,
        model=state["reader_model"],
    )
    run_dir = Path(state["run_dir"])
    cg_path = run_dir / "03_concept_graph.json"
    cg_path.write_text(graph.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    print(f"  → ConceptGraph: {len(graph.concepts)} concepts, "
          f"{len(graph.relations)} relations, {len(graph.aporias)} aporias", flush=True)

    steps = list(state.get("thinking_log", []))
    steps.append({"layer": "analyst", "node": "synthesize_graph", "action": "synthesize",
                  "reasoning": f"Synthesized {len(graph.concepts)} concepts"})
    return {"concept_graph_path": str(cg_path), "thinking_log": steps}


def node_web_research(state: CogitoState) -> dict:
    event_log.step("orchestrator/graph", "→ node: web_research")
    from cogito.services.web_researcher.cli import run as wr_run

    run_dir = Path(state["run_dir"])
    cg_path = run_dir / "03_concept_graph.json"

    book_config = state.get("book_config", {})
    book_name = book_config.get("_name")
    work_description = state.get("work_description", "")
    author = book_config.get("book", {}).get("author", "")

    graph = wr_run(
        output_path=cg_path,
        model=state["reader_model"],
        guide_model=state["dramaturg_model"],
        book=book_name,
        subject=work_description,
        author=author,
    )

    steps = list(state.get("thinking_log", []))
    steps.append({"layer": "web_researcher", "node": "web_research", "action": "research",
                  "reasoning": f"Web research complete: {len(graph.concepts)} concepts"})
    return {"concept_graph_path": str(cg_path), "thinking_log": steps}


def node_produce(state: CogitoState) -> dict:
    event_log.step("orchestrator/graph", "→ node: produce")
    from cogito.services.producer.cli import run as producer_run

    run_dir = Path(state["run_dir"])
    cg_path = Path(state["concept_graph_path"])

    book_name = state.get("book_config", {}).get("_name")
    syllabus, scripts = producer_run(
        input_path=cg_path,
        output_dir=run_dir,
        fmt="podcast",
        mode=state["mode"],
        topic=state.get("topic"),
        persona_preset=state["persona_config"].get("_preset", "descartes_default"),
        planner_model=state["reader_model"],
        dramaturg_model=state["dramaturg_model"],
        book=book_name,
    )

    steps = list(state.get("thinking_log", []))
    steps.append({"layer": "producer", "node": "produce", "action": "plan_and_script",
                  "reasoning": f"Produced {len(scripts)} episode scripts"})
    return {"scripts": [s.model_dump() for s in scripts], "thinking_log": steps}


def node_evaluate_scripts(state: CogitoState) -> dict:
    from cogito.services.evaluator.evaluator import evaluate_scripts
    return evaluate_scripts(state)


def node_synthesize_audio(state: CogitoState) -> dict:
    from cogito.services.audio.synthesizer import synthesize_audio
    return synthesize_audio(state)


def node_translate(state: CogitoState) -> dict:
    from cogito.services.translator.translator import translate_node
    return translate_node(state)


def _check_translate_noop(state: CogitoState) -> dict:
    return {}


# ── Conditional edge functions ─────────────────────────────────────────────────

def should_start(state: CogitoState) -> str:
    """Route to web_research directly when source type is 'web', else ingest text."""
    source_type = state.get("book_config", {}).get("source", {}).get("type", "")
    if source_type == "web":
        return "web_research"
    return "ingest"


def should_research(state: CogitoState) -> str:
    if state.get("skip_research", False):
        return "produce"
    return "web_research"


def should_eval(state: CogitoState) -> str:
    """Decide whether to run the evaluation node or skip directly to audio routing."""
    if state.get("skip_eval", False):
        if state.get("skip_audio", False):
            return "check_translate"
        return "synthesize_audio"
    return "evaluate_scripts"


def should_regen(state: CogitoState) -> str:
    """Decide whether to regenerate scripts based on evaluation."""
    if state.get("needs_regen", False) and state.get("regen_count", 0) < 2:
        return "produce"  # regenerate (max 2 attempts)
    if state.get("skip_audio", False):
        return "check_translate"
    return "synthesize_audio"


def should_audio(state: CogitoState) -> str:
    if state.get("skip_audio", False):
        return "check_translate"
    return "synthesize_audio"


def should_translate(state: CogitoState) -> str:
    if state.get("skip_translate", False):
        return END
    return "translate"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    """Build and compile the Cogito LangGraph pipeline.

    Pass a SqliteSaver checkpointer to enable resume support.
    """
    graph = StateGraph(CogitoState)

    # Nodes
    graph.add_node("route", lambda s: {})
    graph.add_node("ingest", node_ingest)
    graph.add_node("analyze_chunks", node_analyze_chunks)
    graph.add_node("synthesize_graph", node_synthesize_graph)
    graph.add_node("web_research", node_web_research)
    graph.add_node("produce", node_produce)
    graph.add_node("evaluate_scripts", node_evaluate_scripts)
    graph.add_node("synthesize_audio", node_synthesize_audio)
    graph.add_node("check_translate", _check_translate_noop)
    graph.add_node("translate", node_translate)

    # Entry: route by source type
    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        should_start,
        {
            "ingest": "ingest",
            "web_research": "web_research",
        },
    )

    # Book path: ingest → analyze_chunks → synthesize_graph → (research or produce)
    graph.add_edge("ingest", "analyze_chunks")
    graph.add_edge("analyze_chunks", "synthesize_graph")
    graph.add_conditional_edges(
        "synthesize_graph",
        should_research,
        {
            "web_research": "web_research",
            "produce": "produce",
        },
    )
    graph.add_edge("web_research", "produce")

    # Produce → eval (optional) → regen or audio → translate (optional) → END
    graph.add_conditional_edges(
        "produce",
        should_eval,
        {
            "evaluate_scripts": "evaluate_scripts",
            "synthesize_audio": "synthesize_audio",
            "check_translate": "check_translate",
        },
    )
    graph.add_conditional_edges(
        "evaluate_scripts",
        should_regen,
        {
            "produce": "produce",
            "synthesize_audio": "synthesize_audio",
            "check_translate": "check_translate",
        },
    )
    graph.add_edge("synthesize_audio", "check_translate")
    graph.add_conditional_edges(
        "check_translate",
        should_translate,
        {
            "translate": "translate",
            END: END,
        },
    )
    graph.add_edge("translate", END)

    return graph.compile(checkpointer=checkpointer)
