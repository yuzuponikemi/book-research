"""Shared Pydantic schemas — the service interface contracts."""
from cogito.schemas.chunks import Chunk, ChunksV1
from cogito.schemas.concept_graph import (
    Concept,
    Aporia,
    ConceptRelation,
    ArgumentStructure,
    RhetoricalStrategy,
    ConceptGraphV1,
)
from cogito.schemas.production import (
    Persona,
    PersonaConfig,
    Episode,
    SyllabusV1,
    DialogueLine,
    ScriptV1,
)

__all__ = [
    "Chunk",
    "ChunksV1",
    "Concept",
    "Aporia",
    "ConceptRelation",
    "ArgumentStructure",
    "RhetoricalStrategy",
    "ConceptGraphV1",
    "Persona",
    "PersonaConfig",
    "Episode",
    "SyllabusV1",
    "DialogueLine",
    "ScriptV1",
]
