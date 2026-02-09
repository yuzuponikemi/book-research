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


# --- LangGraph State ---


class CogitoState(TypedDict):
    book_title: str
    raw_chunks: list[str]
    chunk_analyses: list[dict]
    concept_graph: dict
    mode: str
    topic: str | None
    persona_config: dict
    syllabus: dict
    scripts: list[dict]
    thinking_log: list[dict]
    reader_model: str
    dramaturg_model: str
