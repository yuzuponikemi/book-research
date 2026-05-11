"""ConceptGraphV1 — the central interface contract of Project Cogito.

This schema is produced by:
  - Route A: Analyst service  (book text → chunks → concept graph)
  - Route B: WebResearcher service  (web search → directly → concept graph)

It is consumed by:
  - Producer service  (concept graph → podcast scripts / articles)

The Pydantic models here are extended from src/models.py with added
provenance metadata (source_mode, generated_by) to record which route
created the graph.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


# ── Leaf models (same as src/models.py, kept here for service independence) ──

class Concept(BaseModel):
    id: str
    name: str
    description: str
    original_quotes: list[str] = Field(default_factory=list)
    source_chunk: str = Field(
        description="ID of the chunk or heading this concept was extracted from. "
                    "Use 'COMBINED' when merged from multiple chunks."
    )


class Aporia(BaseModel):
    id: str
    question: str
    context: str
    related_concepts: list[str] = Field(default_factory=list)


class ConceptRelation(BaseModel):
    source: str
    target: str
    relation_type: Literal["depends_on", "contradicts", "evolves_into"]
    evidence: str


class ArgumentStructure(BaseModel):
    id: str
    premises: list[str]
    conclusion: str
    argument_type: Literal["deductive", "inductive", "analogical"]
    source_chunk: str


class RhetoricalStrategy(BaseModel):
    id: str
    strategy_type: Literal["metaphor", "analogy", "thought_experiment", "appeal_to_authority"]
    description: str
    original_quote: str
    source_chunk: str


# ── Root schema ───────────────────────────────────────────────────────────────

class ConceptGraphV1(BaseModel):
    """Root schema for the unified concept graph (schema version 1).

    This is the single convergence point for all input routes and the
    single entry point for all output (Producer) services.
    """

    schema_version: str = Field(default="1.0")
    subject: str = Field(
        description="Human-readable description of the subject matter, "
                    "e.g. '方法序説 by デカルト'."
    )
    source_mode: Literal["book", "web_researcher"] = Field(
        description="Which input route produced this graph."
    )
    generated_by: Literal["analyst", "web_researcher"] = Field(
        description="Which service generated this graph. "
                    "'analyst' = text chunks were processed by Analyst; "
                    "'web_researcher' = WebResearcher built it directly."
    )

    # Core graph data
    concepts: list[Concept]
    relations: list[ConceptRelation]
    aporias: list[Aporia]
    logic_flow: str
    core_frustration: str

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_legacy_dict(self) -> dict:
        """Return a plain dict compatible with the legacy src/models.ConceptGraph format.

        Useful for passing to existing Director/Dramaturg nodes during migration.
        """
        return {
            "concepts": [c.model_dump() for c in self.concepts],
            "relations": [r.model_dump() for r in self.relations],
            "aporias": [a.model_dump() for a in self.aporias],
            "logic_flow": self.logic_flow,
            "core_frustration": self.core_frustration,
        }

    @classmethod
    def from_legacy_dict(
        cls,
        data: dict,
        *,
        subject: str,
        source_mode: Literal["book", "web_researcher"] = "book",
        generated_by: Literal["analyst", "web_researcher"] = "analyst",
    ) -> "ConceptGraphV1":
        """Construct from a legacy src/models.ConceptGraph dict.

        Used to wrap outputs from the existing pipeline during the migration period.
        """
        # Normalise source_chunk in each concept to prevent Pydantic ValidationErrors:
        #   - missing → default to "COMBINED" (synthesizer merges across chunks)
        #   - non-string → cast to str
        safe_concepts = []
        for c in data.get("concepts", []):
            c = dict(c)  # shallow copy to avoid mutating caller's data
            if "source_chunk" not in c:
                c["source_chunk"] = "COMBINED"
            elif not isinstance(c["source_chunk"], str):
                c["source_chunk"] = str(c["source_chunk"])
            # original_quotes must be a list; LLM sometimes returns "" or a string
            oq = c.get("original_quotes", [])
            if isinstance(oq, str):
                c["original_quotes"] = [oq] if oq.strip() else []
            elif not isinstance(oq, list):
                c["original_quotes"] = []
            safe_concepts.append(c)

        # Normalise relations: drop any entry whose relation_type is not in the
        # allowed Literal.  Callers should normalise before calling this method
        # (see analyst/synthesizer._RELATION_MAP and web_researcher/synthesizer
        # ._RELATION_MAP), but this is a final safety net so a single bad
        # relation never crashes the whole pipeline.
        _valid_rt = {"depends_on", "contradicts", "evolves_into"}
        safe_relations = []
        for r in data.get("relations", []):
            rt = r.get("relation_type") if isinstance(r, dict) else None
            if rt in _valid_rt:
                safe_relations.append(r)
            # silently drop relations with an invalid / missing relation_type

        # Normalise aporias: drop any entry that is not a valid dict.
        safe_aporias = [
            a for a in data.get("aporias", []) if isinstance(a, dict)
        ]

        return cls(
            subject=subject,
            source_mode=source_mode,
            generated_by=generated_by,
            concepts=safe_concepts,
            relations=safe_relations,
            aporias=safe_aporias,
            logic_flow=data.get("logic_flow", ""),
            core_frustration=data.get("core_frustration", ""),
        )

    def concept_ids(self) -> list[str]:
        return [c.id for c in self.concepts]

    def aporia_ids(self) -> list[str]:
        return [a.id for a in self.aporias]
