# Project Cogito — Pipeline Guide

> 日本語版: [PIPELINE_ja.md](PIPELINE_ja.md)

## Quick Start

```bash
# Activate virtual environment
source .venv/bin/activate

# Start Ollama (Apple Silicon)
OLLAMA_KEEP_ALIVE=120m OLLAMA_NUM_PARALLEL=1 ollama serve

# Run: book text → podcast scripts (default mode)
python -m cogito.orchestrator --book descartes_discourse --mode essence

# Run: web research → podcast scripts (no text needed)
python -m cogito.orchestrator --source web --subject "Nietzsche's Thus Spoke Zarathustra" --mode curriculum

# Resume an interrupted run
python -m cogito.orchestrator --resume run_20260301_120000
```

---

## Architecture Overview

Two input routes merge at the Producer stage:

```
Route A (book text):
  Book Config YAML → [Ingestor] → ChunksV1
                   → [Analyst]  → ConceptGraphV1 ─┐
                                                   ├→ [Producer] → Syllabus + Scripts
Route B (web search):                              │
  Subject / Author → [WebResearcher] → ConceptGraphV1 ─┘

Post-processing (both routes):
  Scripts → [Audio] → MP3 files (VOICEVOX)
  Outputs → [Translator] → *_ja.md files
```

The full pipeline is orchestrated via **LangGraph** (`cogito/orchestrator/graph.py`) with SQLite checkpointing for resume support. All services are independent modules in `cogito/services/`.

---

## CLI Options

| Flag | Default | Description |
|---|---|---|
| `--book BOOK` | — | Book config name (mutually exclusive with `--subject`) |
| `--subject TEXT` | — | Free-form subject string (Route B without book config) |
| `--from-graph PATH` | — | Skip ingestion; start from an existing `ConceptGraphV1` JSON |
| `--resume RUN_ID` | — | Resume an interrupted run from its LangGraph checkpoint |
| `--source` | `book` | `book` (Route A) or `web` (Route B) |
| `--mode` | `essence` | `essence` (1 episode) / `curriculum` (3-6 episodes) / `topic` (1-2 focused) |
| `--topic TEXT` | — | Required when `--mode topic` |
| `--persona` | `descartes_default` | Persona preset from `config/personas.yaml` |
| `--reader-model` | `llama3` | Ollama model for analysis and planning |
| `--dramaturg-model` | `qwen3-next` | Ollama model for Japanese script generation |
| `--translator-model` | `translategemma:12b` | Ollama model for EN→JA translation |
| `--skip-research` | — | Skip web research stage (Route A only) |
| `--skip-audio` | — | Skip VOICEVOX audio synthesis |
| `--skip-translate` | — | Skip Japanese translation |

---

## Output Files

Each run creates a timestamped directory under `data/`:

```
data/run_YYYYMMDD_HHMMSS/
  01_chunks.json               ← ChunksV1 (Route A only)
  02_chunk_analyses.json       ← Per-chunk concept extraction (Route A only)
  03_concept_graph.json        ← ConceptGraphV1 (both routes)
  04_syllabus.json             ← SyllabusV1 (episode plan)
  05_scripts.json              ← list[ScriptV1] (dialogue scripts)
  06_audio/                    ← MP3 files (if not --skip-audio)
    ep01.mp3
    ...
  06_audio.json                ← Audio synthesis metadata
  02_chunk_analyses_ja.md      ← Japanese translation (if not --skip-translate)
  03_concept_graph_ja.md
  04_syllabus_ja.md

data/checkpoints.db            ← LangGraph SQLite checkpoints (for --resume)
logs/run_YYYYMMDD_HHMMSS.json  ← Full thinking log (all LLM prompts/responses)
```

---

## Running Individual Services

Each service can be run independently for debugging or partial re-runs:

```bash
# Ingestor: book config → ChunksV1
python -m cogito.services.ingestor \
    --book descartes_discourse \
    --output data/run_xxx/01_chunks.json

# Analyst: ChunksV1 → ConceptGraphV1
python -m cogito.services.analyst \
    --input  data/run_xxx/01_chunks.json \
    --output data/run_xxx/03_concept_graph.json

# WebResearcher: subject → ConceptGraphV1
python -m cogito.services.web_researcher \
    --subject "Kant's Critique of Pure Reason" \
    --output  data/run_xxx/03_concept_graph.json

# Producer: ConceptGraphV1 → Syllabus + Scripts
python -m cogito.services.producer \
    --input  data/run_xxx/03_concept_graph.json \
    --output data/run_xxx/ \
    --mode   curriculum
```

---

## Model Selection

| Role | Recommended | Minimum |
|---|---|---|
| Analysis / Planning (`--reader-model`) | `command-r` 18GB | `llama3` 4.7GB |
| Script writing (`--dramaturg-model`) | `qwen3-next` 50GB | `llama3` 4.7GB |
| Translation (`--translator-model`) | `translategemma:12b` | — |

---

## Configuration

- **Book configs**: `config/books/<name>.yaml` — defines source, chunking, research queries
- **Persona presets**: `config/personas.yaml` — defines characters, voice IDs

Available persona presets: `descartes_default`, `socratic`, `debate`

---

## Further Reading

- [Architecture](docs/architecture-v2.md) — service design, schemas, data flow
- [Usage Guide](docs/usage-guide-v2.md) — full CLI reference, configuration examples
- [Data Schema Reference](docs/data-schema-reference.md) — Pydantic schema details
- [Debugging Guide](docs/debugging-guide.md) — how to trace LLM calls and fix issues
