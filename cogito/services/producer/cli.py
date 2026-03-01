"""Producer service CLI.

Takes a ConceptGraphV1 JSON, generates a syllabus and podcast scripts.

Usage:
    python -m cogito.services.producer \\
        --input    data/run_xxx/03_concept_graph.json \\
        --output   data/run_xxx/ \\
        --format   podcast \\
        --mode     essence \\
        --persona  descartes_default \\
        --planner-model   llama3 \\
        --dramaturg-model qwen3-next

    # With a topic focus:
    python -m cogito.services.producer \\
        --input  data/run_xxx/03_concept_graph.json \\
        --output data/run_xxx/ \\
        --mode   topic \\
        --topic  "心身二元論"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

import yaml

from cogito.schemas.concept_graph import ConceptGraphV1
from cogito.schemas.production import PersonaConfig, SyllabusV1, ScriptV1
from cogito.services.producer.planner import plan_syllabus
from cogito.services.producer.podcast import write_podcast_scripts


CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


def _load_persona(preset_name: str) -> PersonaConfig:
    personas_path = CONFIG_DIR / "personas.yaml"
    with open(personas_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    presets = config.get("presets", {})
    if preset_name not in presets:
        available = ", ".join(presets.keys())
        raise ValueError(f"Unknown persona preset '{preset_name}'. Available: {available}")
    data = presets[preset_name]
    return PersonaConfig(**data)


def _load_book_meta(book: str | None) -> tuple[str | None, str | None, str | None, list[str]]:
    """Returns (book_title, book_title_ja, author_ja, key_terms)."""
    if not book:
        return None, None, None, []
    try:
        from cogito.config.book_config import load_book_config
        bc = load_book_config(book)
        bk = bc.get("book", {})
        return (
            bk.get("title"),
            bk.get("title_ja"),
            bk.get("author_ja", bk.get("author")),
            bc.get("context", {}).get("key_terms", []),
        )
    except Exception:
        return None, None, None, []


def run(
    input_path: Path,
    output_dir: Path,
    fmt: Literal["podcast"] = "podcast",
    mode: Literal["essence", "curriculum", "topic"] = "essence",
    topic: str | None = None,
    persona_preset: str = "descartes_default",
    planner_model: str = "llama3",
    dramaturg_model: str = "qwen3-next",
    book: str | None = None,
) -> tuple[SyllabusV1, list[ScriptV1]]:
    """Programmatic entry point."""

    # ── Load ConceptGraphV1 ───────────────────────────────────────────────────
    print(f"  Loading concept graph from {input_path} ...", flush=True)
    raw = json.loads(input_path.read_text(encoding="utf-8"))

    # Support both native ConceptGraphV1 and legacy format
    if "schema_version" in raw and "source_mode" in raw:
        graph = ConceptGraphV1.model_validate(raw)
    else:
        graph = ConceptGraphV1.from_legacy_dict(
            raw, subject=raw.get("subject", "unknown"), source_mode="book", generated_by="analyst"
        )

    # ── Load configs ──────────────────────────────────────────────────────────
    persona_config = _load_persona(persona_preset)
    book_title, book_title_ja, author_ja, key_terms = _load_book_meta(book)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Plan syllabus ─────────────────────────────────────────────────
    print(f"  Planning syllabus (mode={mode}, model={planner_model}) ...", flush=True)
    syllabus, plan_log = plan_syllabus(
        graph=graph, mode=mode, topic=topic,
        work_description=book_title or graph.subject,
        key_terms=key_terms or None,
        model=planner_model,
    )

    syllabus_path = output_dir / "04_syllabus.json"
    syllabus_path.write_text(
        json.dumps(syllabus.to_legacy_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  → {len(syllabus.episodes)} episodes → {syllabus_path}", flush=True)

    # ── Step 2: Write scripts ─────────────────────────────────────────────────
    if fmt == "podcast":
        print(f"  Writing scripts (model={dramaturg_model}) ...", flush=True)
        scripts, script_log = write_podcast_scripts(
            graph=graph, syllabus=syllabus,
            persona_config=persona_config,
            book_title=book_title, book_title_ja=book_title_ja, author_ja=author_ja,
            dramaturg_model=dramaturg_model,
        )

        scripts_path = output_dir / "05_scripts.json"
        scripts_data = [s.to_legacy_dict() for s in scripts]
        scripts_path.write_text(
            json.dumps(scripts_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        total_lines = sum(len(s.dialogue) for s in scripts)
        print(f"  → {len(scripts)} scripts, {total_lines} dialogue lines → {scripts_path}",
              flush=True)
    else:
        scripts = []

    return syllabus, scripts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Producer service: ConceptGraphV1 → Syllabus + Scripts"
    )
    parser.add_argument("--input", required=True, metavar="PATH",
                        help="Path to ConceptGraphV1 JSON (03_concept_graph.json)")
    parser.add_argument("--output", required=True, metavar="DIR",
                        help="Output directory for syllabus and scripts")
    parser.add_argument("--format", default="podcast", choices=["podcast"],
                        dest="fmt", help="Output format (default: podcast)")
    parser.add_argument("--mode", default="essence",
                        choices=["essence", "curriculum", "topic"],
                        help="Episode planning mode (default: essence)")
    parser.add_argument("--topic", default=None, metavar="TOPIC",
                        help="Topic to focus on (required for topic mode)")
    parser.add_argument("--persona", default="descartes_default", metavar="PRESET",
                        help="Persona preset from config/personas.yaml")
    parser.add_argument("--planner-model", default="llama3", metavar="MODEL",
                        help="Ollama model for syllabus planning (default: llama3)")
    parser.add_argument("--dramaturg-model", default="qwen3-next", metavar="MODEL",
                        help="Ollama model for script writing (default: qwen3-next)")
    parser.add_argument("--book", default=None, metavar="BOOK",
                        help="Book config name for title/author metadata (optional)")
    args = parser.parse_args(argv)

    if args.mode == "topic" and not args.topic:
        parser.error("--topic is required when mode=topic")

    run(
        input_path=Path(args.input),
        output_dir=Path(args.output),
        fmt=args.fmt,
        mode=args.mode,
        topic=args.topic,
        persona_preset=args.persona,
        planner_model=args.planner_model,
        dramaturg_model=args.dramaturg_model,
        book=args.book,
    )


if __name__ == "__main__":
    main()
