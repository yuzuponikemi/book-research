"""Lightweight event log for tracking LLM calls, API calls, and pipeline steps.

Usage (from any service):
    from cogito.utils import event_log

    # Log an LLM call with timing
    t0 = time.time()
    result = llm.invoke(prompt).content
    event_log.llm("web_researcher/aggregator", "summarize", model, time.time() - t0)

    # Log a search API call
    event_log.api("web_researcher/searcher", "tavily", query, n_results, duration_s)

    # Log a pipeline step
    event_log.step("orchestrator", "route → web_research")

Initialised once per run by the orchestrator CLI:
    event_log.init(run_dir=Path("data/run_xxx"))
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path


class _EventLog:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._t0: float = time.time()
        self._run_dir: Path | None = None
        self._llm_counts: dict[str, int] = {}
        self._llm_secs: dict[str, float] = {}
        self._api_counts: dict[str, int] = {}
        self._api_results: dict[str, int] = {}

    def init(self, run_dir: Path) -> None:
        """Reset for a new run. Called once from orchestrator CLI."""
        self._events = []
        self._t0 = time.time()
        self._run_dir = run_dir
        self._llm_counts = {}
        self._llm_secs = {}
        self._api_counts = {}
        self._api_results = {}

    # ── Public logging methods ─────────────────────────────────────────────────

    def step(self, service: str, detail: str) -> None:
        """Log a pipeline step transition (no timing)."""
        self._emit("STEP", service, detail)

    def llm(self, service: str, action: str, model: str, duration_s: float) -> None:
        """Log a completed LLM call."""
        self._llm_counts[model] = self._llm_counts.get(model, 0) + 1
        self._llm_secs[model] = self._llm_secs.get(model, 0.0) + duration_s
        detail = f"{action:<32s} {model:<22s} {duration_s:.1f}s"
        self._emit("LLM ", service, detail)

    def api(self, service: str, engine: str, query: str, n_results: int, duration_s: float) -> None:
        """Log a completed search API call."""
        self._api_counts[engine] = self._api_counts.get(engine, 0) + 1
        self._api_results[engine] = self._api_results.get(engine, 0) + n_results
        q_short = (query[:38] + "…") if len(query) > 40 else query
        detail = f"{engine:<10s} {n_results:3d} hits  \"{q_short}\"  {duration_s:.1f}s"
        self._emit("API ", service, detail)

    def error(self, service: str, detail: str) -> None:
        """Log an error event."""
        self._emit("ERR ", service, detail)

    # ── Summary & persistence ──────────────────────────────────────────────────

    def save(self) -> Path | None:
        """Print run summary and write events.log to run_dir."""
        total_s = time.time() - self._t0
        self._print_summary(total_s)

        if not self._run_dir:
            return None

        lines: list[str] = [
            f"# Cogito event log — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for e in self._events:
            lines.append(
                f"[{_fmt_elapsed(e['elapsed_s']):>7s}] [{e['tag']}] "
                f"{e['service']:<38s} {e['detail']}"
            )

        lines += ["", "# Summary", f"total_time_s: {total_s:.0f}"]
        for model, count in sorted(self._llm_counts.items()):
            lines.append(f"llm.{model}: {count} calls  {self._llm_secs[model]:.0f}s")
        for engine, count in sorted(self._api_counts.items()):
            lines.append(f"api.{engine}: {count} calls  {self._api_results[engine]} results")

        path = self._run_dir / "events.log"
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  events.log → {path}", flush=True)
        return path

    # ── Internal ──────────────────────────────────────────────────────────────

    def _elapsed(self) -> float:
        return time.time() - self._t0

    def _emit(self, tag: str, service: str, detail: str) -> None:
        elapsed = self._elapsed()
        self._events.append({
            "elapsed_s": round(elapsed, 1),
            "tag": tag.strip(),
            "service": service,
            "detail": detail,
        })
        print(
            f"  [{_fmt_elapsed(elapsed):>7s}] [{tag}] {service:<38s} {detail}",
            flush=True,
        )

    def _print_summary(self, total_s: float) -> None:
        llm_total = sum(self._llm_counts.values())
        api_total = sum(self._api_counts.values())
        api_results_total = sum(self._api_results.values())

        print()
        print("  ┌─ Event Summary " + "─" * 44)
        mins, secs = divmod(total_s, 60)
        print(f"  │  Total time : {int(mins)}m {secs:.0f}s")
        if llm_total:
            parts = ",  ".join(
                f"{m}: {c}× ({self._llm_secs[m]:.0f}s)"
                for m, c in sorted(self._llm_counts.items())
            )
            print(f"  │  LLM calls  : {llm_total} total   {parts}")
        if api_total:
            parts = ",  ".join(
                f"{e}: {c}× ({self._api_results[e]} results)"
                for e, c in sorted(self._api_counts.items())
            )
            print(f"  │  API calls  : {api_total} total   {parts}")
        print("  └" + "─" * 59)


def _fmt_elapsed(s: float) -> str:
    mins = int(s // 60)
    secs = s % 60
    return f"{mins}:{secs:04.1f}" if mins > 0 else f"{secs:.1f}s"


# ── Module-level singleton ─────────────────────────────────────────────────────

_instance = _EventLog()


def init(run_dir: Path) -> None:
    """Initialise the event log for a new run. Call once from orchestrator."""
    _instance.init(run_dir)


def step(service: str, detail: str) -> None:
    _instance.step(service, detail)


def llm(service: str, action: str, model: str, duration_s: float) -> None:
    _instance.llm(service, action, model, duration_s)


def api(service: str, engine: str, query: str, n_results: int, duration_s: float) -> None:
    _instance.api(service, engine, query, n_results, duration_s)


def error(service: str, detail: str) -> None:
    _instance.error(service, detail)


def save() -> Path | None:
    return _instance.save()
