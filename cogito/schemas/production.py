"""SyllabusV1 / ScriptV1 — output schema of the Producer service.

Consumed by:
  - Podcast audio synthesis (VOICEVOX)
  - Future: article writers, report generators
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


# ── Persona (input configuration, not produced) ──────────────────────────────

class Persona(BaseModel):
    name: str
    role: str
    description: str
    tone: str
    speaking_style: str


class PersonaConfig(BaseModel):
    persona_a: Persona
    persona_b: Persona


# ── Syllabus (Director output) ────────────────────────────────────────────────

class Episode(BaseModel):
    episode_number: int
    title: str
    theme: str
    concept_ids: list[str] = Field(default_factory=list)
    aporia_ids: list[str] = Field(default_factory=list)
    cliffhanger: str = ""
    cognitive_bridge: str = ""


class SyllabusV1(BaseModel):
    """Episode plan produced by the Director stage of Producer."""

    schema_version: str = Field(default="1.0")
    subject: str
    mode: Literal["essence", "curriculum", "topic"]
    episodes: list[Episode]
    meta_narrative: str

    @classmethod
    def from_legacy_dict(cls, data: dict, *, subject: str) -> "SyllabusV1":
        return cls(
            subject=subject,
            mode=data.get("mode", "essence"),
            episodes=data.get("episodes", []),
            meta_narrative=data.get("meta_narrative", ""),
        )

    def to_legacy_dict(self) -> dict:
        return {
            "mode": self.mode,
            "episodes": [e.model_dump() for e in self.episodes],
            "meta_narrative": self.meta_narrative,
        }


# ── Scripts (Dramaturg output) ────────────────────────────────────────────────

class DialogueLine(BaseModel):
    speaker: str
    line: str


class ScriptV1(BaseModel):
    """Single episode dialogue script produced by the Dramaturg stage of Producer."""

    schema_version: str = Field(default="1.0")
    subject: str
    episode_number: int
    title: str
    opening_bridge: str
    dialogue: list[DialogueLine]
    closing_hook: str

    @classmethod
    def from_legacy_dict(cls, data: dict, *, subject: str) -> "ScriptV1":
        return cls(
            subject=subject,
            episode_number=data.get("episode_number", 1),
            title=data.get("title", ""),
            opening_bridge=data.get("opening_bridge", ""),
            dialogue=[
                DialogueLine(**d) if isinstance(d, dict) else DialogueLine(speaker="?", line=str(d))
                for d in data.get("dialogue", [])
            ],
            closing_hook=data.get("closing_hook", ""),
        )

    def to_legacy_dict(self) -> dict:
        return {
            "episode_number": self.episode_number,
            "title": self.title,
            "opening_bridge": self.opening_bridge,
            "dialogue": [d.model_dump() for d in self.dialogue],
            "closing_hook": self.closing_hook,
        }
