# Project Cogito - Pipeline Guide

## Quick Start

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run with defaults (essence mode, descartes_default persona)
python3 main.py

# Run with specific options
python3 main.py --mode curriculum --persona socratic
python3 main.py --mode topic --topic "cogito ergo sum" --persona debate

# Specify different Ollama models
python3 main.py --reader-model command-r --dramaturg-model qwen3-next
```

### CLI Options

| Flag | Default | Description |
|---|---|---|
| `--mode` | `essence` | `essence` (1 episode, core idea), `curriculum` (3-5 episodes), `topic` (focused) |
| `--persona` | `descartes_default` | Persona preset from `config/personas.yaml` |
| `--topic` | - | Required for `topic` mode |
| `--reader-model` | `llama3` | Ollama model for analysis/planning (needs JSON capability) |
| `--dramaturg-model` | `qwen3-next` | Ollama model for Japanese dialogue generation |
| `--skip-research` | - | Skip research/critique/enrichment stages |
| `--skip-audio` | - | Skip VOICEVOX audio synthesis stage |
| `--skip-translate` | - | Skip Japanese translation stage |
| `--trace` | - | Launch local Arize Phoenix UI for LLM call tracing |
| `--resume` | - | Resume from a previous run checkpoint (pass run ID) |
| `--from-node` | - | Re-execute from this node onward (requires `--resume`) |

---

## Pipeline Stages

Each run creates a timestamped directory under `data/` with human-readable `.md` files
and machine-readable `.json` files for every stage:

```
data/run_YYYYMMDD_HHMMSS/
  01_chunks.md           <- Ingested text chunks
  01_chunks.json
  02_chunk_analyses.md   <- Per-chunk concept extraction
  02_chunk_analyses.json
  03_concept_graph.md    <- Unified concept graph
  03_concept_graph.json
  04_syllabus.md         <- Episode plan
  04_syllabus.json
  05_scripts.md          <- Final dialogue scripts
  05_scripts.json

logs/run_YYYYMMDD_HHMMSS.json  <- Full thinking log (all LLM prompts/responses)
```

### Stage 1: Ingestion (`01_chunks`)

**What it does:** Downloads Descartes' "Discourse on the Method" from Project Gutenberg,
strips boilerplate, and splits into 6 semantic chunks (Parts I-VI).

**What to check:**
- Are all 6 parts present?
- Are the chunks roughly the right size? (PART I ~15K chars, PART V ~32K chars)
- Open `01_chunks.md` to see a preview of each chunk

**No LLM calls** — this is deterministic text processing.

### Stage 2: Analysis (`02_chunk_analyses`)

**What it does:** Sends each chunk to the Reader model (llama3) with a hermeneutic
analysis prompt. Extracts concepts, aporias (unresolved tensions), relations, and
logic flow per chunk.

**What to check in `02_chunk_analyses.md`:**
- Does each chunk have concepts? (Expect 3-6 per chunk)
- Are the concepts **philosophical**, not just topic summaries?
- Check Part IV especially: should find `cogito_ergo_sum`, `methodical_doubt`
- Are the quotes actually from the text, not hallucinated?
- Do the relations make sense? (e.g., `methodical_doubt` --> `cogito_ergo_sum`)

**Common issues:**
- 0 concepts for a chunk = JSON parsing failed. Check the thinking log for `llm_raw_response`
- Shallow concepts = model too small. Try `command-r` as reader model.

### Stage 3: Synthesis (`03_concept_graph`)

**What it does:** Merges all 6 chunk analyses into one unified concept graph.
Deduplicates concepts, builds cross-chunk relations, identifies the `core_frustration`.

**What to check in `03_concept_graph.md`:**
- Are cross-chunk concepts deduplicated? (e.g., `methodical_doubt` appears in Parts I, II, IV, VI
  but should appear once in the unified graph)
- Is the `core_frustration` a real intellectual tension, not a generic summary?
- Does the `logic_flow` tell a coherent story from Part I to Part VI?
- Are there cross-part relations? (e.g., Part I's doubt -> Part IV's cogito)

**Expected key concepts for Descartes:**
- methodical doubt, cogito ergo sum, clear and distinct perception,
  mind-body dualism, proof of God's existence

### Stage 4: Planning (`04_syllabus`)

**What it does:** Generates an episode plan based on the mode:
- **essence**: 1 episode capturing the core tension
- **curriculum**: 3-5 episodes following the logical progression of ideas
- **topic**: 1-2 episodes focused on a specific topic

**What to check in `04_syllabus.md`:**
- Does the `cognitive_bridge` connect 17th-century philosophy to modern life?
- Are the `concept_ids` and `aporia_ids` referencing real concepts from the graph?
- Does the `cliffhanger` make you want to listen more?

### Stage 5: Scriptwriting (`05_scripts`)

**What it does:** Generates Japanese dialogue using the selected persona preset
and the Dramaturg model (qwen3-next).

**What to check in `05_scripts.md`:**
- Does the dialogue sound natural in Japanese? (not machine-translated)
- Are the two characters distinguishable in voice and tone?
- Are original Descartes quotes integrated naturally?
- Does the `opening_bridge` set context? Does the `closing_hook` create anticipation?

**Persona differences:** Running with different `--persona` values should produce
noticeably different dialogue styles:
- `descartes_default`: Modern skeptic vs. ghost of Descartes
- `socratic`: Eager student vs. Socratic mentor
- `debate`: Passionate advocate vs. rigorous critic

---

## Thinking Log

The thinking log at `logs/run_YYYYMMDD_HHMMSS.json` contains the full record of
every decision the pipeline made. Each step includes:

```json
{
  "timestamp": "2026-02-09T01:01:31.123456",
  "layer": "reader",
  "node": "analyst",
  "action": "analyze_chunk:PART IV",
  "input_summary": "Chunk 'PART IV': 15597 chars",
  "llm_prompt": "You are a philosopher performing hermeneutic analysis...",
  "llm_raw_response": "{ \"concepts\": [...] }",
  "parsed_output": { ... },
  "error": null,
  "reasoning": "Extracted 5 concepts, 1 aporias, 3 relations from PART IV"
}
```

### How to trace a concept

1. Find the concept in `03_concept_graph.json` (e.g., `cogito_ergo_sum`)
2. Note its `source_chunk` (e.g., `PART IV`)
3. Open the thinking log, find the step with `action: "analyze_chunk:PART IV"`
4. Read the `llm_prompt` to see exactly what the model was asked
5. Read the `llm_raw_response` to see the raw model output
6. Compare `parsed_output` to understand if parsing lost anything

### How to debug a missing concept

1. Check `02_chunk_analyses.json` — was the concept extracted at the chunk level?
   - If no: the analyst prompt needs tuning, or the chunk was truncated
   - If yes: the synthesizer merged it away. Check the synthesizer step in the log.
2. Look at the synthesizer step's `llm_raw_response` to see its merge decisions

---

## Model Selection Guide

| Role | Recommended | Minimum | Notes |
|---|---|---|---|
| Reader/Director | `command-r` (18GB) | `llama3` (4.7GB) | Larger = better concept extraction |
| Dramaturg | `qwen3-next` (50GB) | `llama3` (4.7GB) | Qwen models excel at Japanese |

The Reader model needs to produce valid JSON, so `format="json"` is enabled for all
Reader/Director calls. The Dramaturg model generates freeform text that happens to
contain JSON, so JSON mode is not forced there.

---

## Persona Configuration

Edit `config/personas.yaml` to create new persona presets or modify existing ones.
Each preset defines two characters (`persona_a` and `persona_b`) with:

- `name`: Character name used in dialogue
- `role`: Role description (in Japanese)
- `description`: Full character description
- `tone`: Speaking tone (in Japanese)
- `speaking_style`: How the character talks

The persona descriptions are injected directly into the Dramaturg prompt, so
writing them in a mix of Japanese and English works well — the Japanese parts
guide the model's output tone, while English parts provide clear instructions.
