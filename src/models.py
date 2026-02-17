"""Pydantic models and LangGraph state for Project Cogito."""

from typing import TypedDict

from pydantic import BaseModel


# --- Concept Graph (Heart of the system) ---


class Concept(BaseModel):
    id: str
    name: str
    description: str
    original_quotes: list[str]
    source_chunk: str


class Aporia(BaseModel):
    id: str
    question: str
    context: str
    related_concepts: list[str]


class ConceptRelation(BaseModel):
    source: str
    target: str
    relation_type: str  # "depends_on" | "contradicts" | "evolves_into"
    evidence: str


class ArgumentStructure(BaseModel):
    id: str
    premises: list[str]
    conclusion: str
    argument_type: str  # "deductive" | "inductive" | "analogical"
    source_chunk: str


class RhetoricalStrategy(BaseModel):
    id: str
    strategy_type: str  # "metaphor" | "analogy" | "thought_experiment" | "appeal_to_authority"
    description: str
    original_quote: str
    source_chunk: str


class ConceptGraph(BaseModel):
    concepts: list[Concept]
    relations: list[ConceptRelation]
    aporias: list[Aporia]
    logic_flow: str
    core_frustration: str


# --- Persona (configurable) ---


class Persona(BaseModel):
    name: str
    role: str
    description: str
    tone: str
    speaking_style: str


class PersonaConfig(BaseModel):
    persona_a: Persona
    persona_b: Persona


# --- Director output ---


class Episode(BaseModel):
    episode_number: int
    title: str
    theme: str
    concept_ids: list[str]
    aporia_ids: list[str]
    cliffhanger: str
    cognitive_bridge: str


class Syllabus(BaseModel):
    mode: str  # "essence" | "curriculum" | "topic"
    episodes: list[Episode]
    meta_narrative: str


# --- Dramaturg output ---


class DialogueLine(BaseModel):
    speaker: str
    line: str


class Script(BaseModel):
    episode_number: int
    title: str
    opening_bridge: str
    dialogue: list[DialogueLine]
    closing_hook: str


# --- Audio output ---


class AudioEpisodeMetadata(BaseModel):
    episode_number: int
    title: str
    file: str | None
    duration_sec: float
    file_size_bytes: int
    lines_synthesized: int
    errors: int
    synthesis_time_sec: float


# --- LangGraph State ---


class CogitoState(TypedDict):
    # Configuration
    book_config: dict
    book_title: str
    mode: str
    topic: str | None
    persona_config: dict
    reader_model: str
    dramaturg_model: str
    translator_model: str
    work_description: str

    # Run metadata (str because Path is not serialisable)
    run_dir: str
    run_id: str

    # Flags
    skip_research: bool
    skip_audio: bool
    skip_translate: bool
    deep_analysis: bool

    # Data Artifacts
    raw_chunks: list[str]
    chunk_analyses: list[dict]
    concept_graph: dict
    research_context: dict
    critique_report: dict
    enrichment: dict
    reading_material: str
    syllabus: dict
    scripts: list[dict]
    audio_metadata: list[dict]

    # Logging
    thinking_log: list[dict]
