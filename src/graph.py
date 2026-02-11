"""LangGraph wiring: Reader → Researcher → Director → Dramaturg with logging."""

from langgraph.graph import StateGraph, END

from src.models import CogitoState
from src.reader.ingestion import ingest
from src.reader.analyst import analyze_chunks
from src.reader.synthesizer import synthesize
from src.researcher.researcher import research
from src.critic.critic import critique
from src.director.enricher import enrich
from src.researcher.reading_material import generate_reading_material
from src.director.planner import plan
from src.dramaturg.scriptwriter import write_scripts
from src.audio.synthesizer import synthesize_audio


def should_research(state: CogitoState) -> str:
    """Condition for research stage."""
    if state.get("skip_research", False):
        return "plan"
    return "research"


def should_audio(state: CogitoState) -> str:
    """Condition for audio synthesis stage."""
    if state.get("skip_audio", False):
        return END
    return "synthesize_audio"


def build_graph() -> StateGraph:
    """Build the full Cogito pipeline graph.

    Topology:
        ingest → analyze_chunks → synthesize 
          → (if not skip_research) → research → critique → enrich → generate_reading_material → plan
          → (if skip_research) → plan
        plan → write_scripts 
          → (if not skip_audio) → synthesize_audio → END
          → (if skip_audio) → END
    """
    graph = StateGraph(CogitoState)

    # --- Layer 1: Reader ---
    graph.add_node("ingest", ingest)
    graph.add_node("analyze_chunks", analyze_chunks)
    graph.add_node("synthesize", synthesize)

    # --- Layer 2: Researcher (Optional) ---
    graph.add_node("research", research)
    graph.add_node("critique", critique)
    graph.add_node("enrich", enrich)
    graph.add_node("generate_reading_material", generate_reading_material)

    # --- Layer 3: Director ---
    graph.add_node("plan", plan)

    # --- Layer 4: Dramaturg ---
    graph.add_node("write_scripts", write_scripts)
    graph.add_node("synthesize_audio", synthesize_audio)

    # --- Edges ---
    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "analyze_chunks")
    graph.add_edge("analyze_chunks", "synthesize")
    
    # Conditional branching for Research
    graph.add_conditional_edges(
        "synthesize",
        should_research,
        {
            "research": "research",
            "plan": "plan"
        }
    )

    # Research loop
    graph.add_edge("research", "critique")
    graph.add_edge("critique", "enrich")
    graph.add_edge("enrich", "generate_reading_material")
    graph.add_edge("generate_reading_material", "plan")

    # Planning to Scripting
    graph.add_edge("plan", "write_scripts")

    # Conditional branching for Audio
    graph.add_conditional_edges(
        "write_scripts",
        should_audio,
        {
            "synthesize_audio": "synthesize_audio",
            END: END
        }
    )

    graph.add_edge("synthesize_audio", END)

    return graph.compile()
