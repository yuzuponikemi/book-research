"""Thinking log system for traceability across the pipeline."""

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


LOGS_DIR = Path(__file__).parent.parent / "logs"


class ThinkingStep(BaseModel):
    timestamp: str = ""
    layer: str = ""  # "reader" | "director" | "dramaturg" | "audio"
    node: str = ""  # e.g., "analyst", "synthesizer", "planner"
    action: str = ""
    input_summary: str = ""
    llm_prompt: str = ""
    llm_raw_response: str = ""
    parsed_output: dict | None = None
    error: str | None = None
    reasoning: str = ""


class ThinkingLog(BaseModel):
    run_id: str
    started_at: str
    book_title: str
    mode: str
    steps: list[ThinkingStep]
    final_concept_graph: dict | None
    final_syllabus: dict | None


def make_run_id() -> str:
    return datetime.now().strftime("run_%Y%m%d_%H%M%S")


def create_step(
    *,
    layer: str,
    node: str,
    action: str,
    input_summary: str,
    llm_prompt: str = "",
    llm_raw_response: str = "",
    parsed_output: dict | None = None,
    error: str | None = None,
    reasoning: str = "",
) -> dict:
    """Create a ThinkingStep as a dict for inclusion in state."""
    step = ThinkingStep(
        timestamp=datetime.now().isoformat(),
        layer=layer,
        node=node,
        action=action,
        input_summary=input_summary,
        llm_prompt=llm_prompt,
        llm_raw_response=llm_raw_response,
        parsed_output=parsed_output,
        error=error,
        reasoning=reasoning,
    )
    return step.model_dump()


def extract_json(text: str) -> dict:
    """Extract JSON from LLM output, handling various formats.

    Tries in order:
    1. ```json ... ``` code fences
    2. ``` ... ``` code fences
    3. First { to last } (bare JSON with text preamble)
    """
    # Try code fences first
    if "```json" in text:
        json_text = text.split("```json")[1].split("```")[0]
        return json.loads(json_text.strip())
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            json_text = parts[1]
            # Strip optional language tag on first line
            if json_text.startswith(("json", "JSON")):
                json_text = json_text[4:]
            return json.loads(json_text.strip())

    # Fallback: find outermost { ... }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return json.loads(text[first_brace:last_brace + 1])

    raise json.JSONDecodeError("No JSON object found in response", text, 0)


def flush_log(
    *,
    run_id: str,
    book_title: str,
    mode: str,
    steps: list[dict],
    concept_graph: dict | None = None,
    syllabus: dict | None = None,
) -> Path:
    """Write the accumulated thinking log to a JSON file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log = ThinkingLog(
        run_id=run_id,
        started_at=steps[0]["timestamp"] if steps else datetime.now().isoformat(),
        book_title=book_title,
        mode=mode,
        steps=[ThinkingStep(**s) for s in steps],
        final_concept_graph=concept_graph,
        final_syllabus=syllabus,
    )

    path = LOGS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(log.model_dump(), ensure_ascii=False, indent=2))
    return path
