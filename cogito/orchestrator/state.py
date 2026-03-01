"""LangGraph state definition for the Cogito pipeline."""

from typing import TypedDict


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

    # Data Artifacts
    chunk_tuples: list  # list[(chunk_id, text)]
    chunk_analyses: list[dict]
    concept_graph_path: str   # path to saved ConceptGraphV1 JSON
    scripts: list[dict]
    audio_metadata: list[dict]

    # Logging
    thinking_log: list[dict]
