"""LangGraph wiring: Reader → Director → Dramaturg with logging."""

from langgraph.graph import StateGraph, END

from src.models import CogitoState
from src.reader.ingestion import ingest
from src.reader.analyst import analyze_chunks
from src.reader.synthesizer import synthesize
from src.director.planner import plan
from src.dramaturg.scriptwriter import write_scripts


def build_graph() -> StateGraph:
    """Build the full Cogito pipeline graph.

    Topology:
        ingest → analyze_chunks → synthesize → plan → write_scripts → END
    """
    graph = StateGraph(CogitoState)

    # Add nodes
    graph.add_node("ingest", ingest)
    graph.add_node("analyze_chunks", analyze_chunks)
    graph.add_node("synthesize", synthesize)
    graph.add_node("plan", plan)
    graph.add_node("write_scripts", write_scripts)

    # Wire edges: linear pipeline
    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "analyze_chunks")
    graph.add_edge("analyze_chunks", "synthesize")
    graph.add_edge("synthesize", "plan")
    graph.add_edge("plan", "write_scripts")
    graph.add_edge("write_scripts", END)

    return graph.compile()
