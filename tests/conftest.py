"""Shared fixtures and configuration for all tests.

Usage:
    pytest tests/ -m "not integration"   # fast, no LLM
    pytest tests/ -m integration -v      # uses llama3.2:latest
"""

import json
import tempfile
from pathlib import Path

import pytest

# ── Model names ───────────────────────────────────────────────────────────────
# Override via env var COGITO_TEST_MODEL if needed
import os
DEFAULT_MODEL = os.environ.get("COGITO_TEST_MODEL", "llama3.2:latest")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: requires Ollama LLM (llama3.2)")


# ── Sample data (no LLM required) ─────────────────────────────────────────────

SAMPLE_TEXT = """\
PART I

Good sense is, of all things among men, the most equally distributed; for every one
thinks himself so abundantly provided with it, that those even who are the most
difficult to satisfy in everything else, do not usually desire a larger measure of
this quality than they already possess.

PART II

I was then in Germany, attracted thither by the wars in that country, which have not
yet been brought to a termination; and as I was returning to the army from the
coronation of the Emperor, the setting in of winter arrested me in a locality where,
as I found no society to interest me, I was also happily undisturbed by any cares or
passions.
"""

SAMPLE_CHUNK_ANALYSIS = {
    "concepts": [
        {
            "id": "good_sense",
            "name": "Good Sense",
            "description": "The capacity to judge correctly, distributed equally among all humans.",
            "original_quotes": ["Good sense is, of all things among men, the most equally distributed"],
            "source_chunk": "PART I",
        },
        {
            "id": "methodical_doubt",
            "name": "Methodical Doubt",
            "description": "The systematic rejection of uncertain beliefs to reach certain foundations.",
            "original_quotes": ["I was also happily undisturbed by any cares or passions"],
            "source_chunk": "PART II",
        },
    ],
    "aporias": [
        {
            "id": "certainty_vs_action",
            "question": "How can one act while doubting everything?",
            "context": "If all knowledge is uncertain, action seems impossible.",
            "related_concepts": ["good_sense", "methodical_doubt"],
        }
    ],
    "relations": [
        {
            "source": "good_sense",
            "target": "methodical_doubt",
            "relation_type": "depends_on",
            "evidence": "Clear reasoning enables systematic doubt.",
        }
    ],
    "logic_flow": "Descartes begins by affirming equal reason among humans, then retreats to solitude to systematically rebuild knowledge.",
}

SAMPLE_CONCEPT_GRAPH_DICT = {
    "concepts": SAMPLE_CHUNK_ANALYSIS["concepts"],
    "relations": SAMPLE_CHUNK_ANALYSIS["relations"],
    "aporias": SAMPLE_CHUNK_ANALYSIS["aporias"],
    "logic_flow": SAMPLE_CHUNK_ANALYSIS["logic_flow"],
    "core_frustration": "The tension between universal reason and the unreliability of tradition.",
}

SAMPLE_SYLLABUS_DICT = {
    "mode": "essence",
    "episodes": [
        {
            "episode_number": 1,
            "title": "The Search for Certainty",
            "theme": "Why does Descartes doubt everything?",
            "concept_ids": ["good_sense", "methodical_doubt"],
            "aporia_ids": ["certainty_vs_action"],
            "cliffhanger": "But if you doubt everything, how do you even get out of bed?",
            "cognitive_bridge": "Like clearing your cache — Descartes wanted a factory reset for knowledge.",
        }
    ],
    "meta_narrative": "A philosopher's quest to rebuild knowledge from scratch.",
}

SAMPLE_PERSONA = {
    "persona_a": {
        "name": "Host",
        "role": "現代の哲学ジャーナリスト",
        "description": "批判的思考をもつ現代人",
        "tone": "好奇心旺盛",
        "speaking_style": "短い質問で相手に考えさせる",
    },
    "persona_b": {
        "name": "Descartes",
        "role": "哲学者の亡霊",
        "description": "17世紀の合理主義哲学者",
        "tone": "論理的・慎重",
        "speaking_style": "演繹的にゆっくりと論を展開する",
    },
    "voice": {"Host": 2, "Descartes": 3, "_default_a": 2, "_default_b": 3},
}


@pytest.fixture
def model() -> str:
    return DEFAULT_MODEL


@pytest.fixture
def sample_text() -> str:
    return SAMPLE_TEXT


@pytest.fixture
def sample_chunk_analysis() -> dict:
    return SAMPLE_CHUNK_ANALYSIS


@pytest.fixture
def sample_concept_graph_dict() -> dict:
    return SAMPLE_CONCEPT_GRAPH_DICT


@pytest.fixture
def sample_syllabus_dict() -> dict:
    return SAMPLE_SYLLABUS_DICT


@pytest.fixture
def sample_persona() -> dict:
    return SAMPLE_PERSONA


@pytest.fixture
def tmp_text_file(tmp_path: Path, sample_text: str) -> Path:
    """Write sample text to a temporary file and return its path."""
    f = tmp_path / "test_book.txt"
    f.write_text(sample_text, encoding="utf-8")
    return f


@pytest.fixture
def concept_graph_v1(sample_concept_graph_dict: dict):
    """Return a ConceptGraphV1 built from sample data."""
    from cogito.schemas.concept_graph import ConceptGraphV1
    return ConceptGraphV1.from_legacy_dict(
        sample_concept_graph_dict,
        subject="Discourse on the Method",
        source_mode="book",
        generated_by="analyst",
    )


@pytest.fixture
def syllabus_v1(sample_syllabus_dict: dict, concept_graph_v1):
    """Return a SyllabusV1 built from sample data."""
    from cogito.schemas.production import SyllabusV1
    return SyllabusV1.from_legacy_dict(
        sample_syllabus_dict,
        subject=concept_graph_v1.subject,
    )


@pytest.fixture
def persona_config(sample_persona: dict):
    from cogito.schemas.production import PersonaConfig
    return PersonaConfig(**sample_persona)
