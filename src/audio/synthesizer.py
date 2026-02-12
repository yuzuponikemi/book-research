"""Audio synthesis pipeline stage: convert Japanese scripts to MP3 via VOICEVOX."""

import io
import json
import time
from pathlib import Path

from pydub import AudioSegment

from src.audio.voicevox_client import VoicevoxClient

# Silence durations (milliseconds)
SILENCE_SAME_SPEAKER_MS = 600
SILENCE_SPEAKER_CHANGE_MS = 800
SILENCE_SECTION_MS = 1800

MP3_BITRATE = "192k"


def _resolve_speaker_id(speaker_name: str, persona_config: dict) -> int:
    """Resolve a speaker name to a VOICEVOX speaker ID.

    Resolution order:
    1. Exact match in persona_config["voice"] name->ID mapping
    2. Fallback: persona_a name -> _default_a, persona_b name -> _default_b
    3. Final fallback: speaker ID 0
    """
    voice_map = persona_config.get("voice", {})

    # 1. Direct name match
    if speaker_name in voice_map:
        return int(voice_map[speaker_name])

    # 2. Match against persona names for defaults
    persona_a_name = persona_config.get("persona_a", {}).get("name", "")
    persona_b_name = persona_config.get("persona_b", {}).get("name", "")

    if speaker_name == persona_a_name and "_default_a" in voice_map:
        return int(voice_map["_default_a"])
    if speaker_name == persona_b_name and "_default_b" in voice_map:
        return int(voice_map["_default_b"])

    # 3. Final fallback
    return 0


def _wav_bytes_to_segment(wav_bytes: bytes) -> AudioSegment:
    """Convert WAV bytes to a pydub AudioSegment."""
    return AudioSegment.from_wav(io.BytesIO(wav_bytes))


def _synthesize_line(client: VoicevoxClient, text: str, speaker_id: int, speed_scale: float = 1.3, intonation_scale: float = 1.5) -> AudioSegment | None:
    """Synthesize a single line of text, returning AudioSegment or None on error."""
    text = text.strip()
    if not text:
        return None
    try:
        wav_data = client.synthesize(text, speaker_id, speed_scale=speed_scale, intonation_scale=intonation_scale)
        return _wav_bytes_to_segment(wav_data)
    except Exception:
        return None


def synthesize_audio(state: dict, speed_scale: float = 1.3, intonation_scale: float = 1.5) -> dict:
    """Pipeline function: convert scripts to MP3 audio files via VOICEVOX.

    Args:
        state: Pipeline state with scripts, persona_config, and run_dir.
        speed_scale: VOICEVOX speedScale (1.0 = normal, 1.3 = faster).
        intonation_scale: VOICEVOX intonationScale (1.0 = normal, higher = more expressive).

    Returns:
        Dict with audio_metadata and updated thinking_log.
    """
    run_dir = Path(state["run_dir"])
    scripts = state.get("scripts", [])
    persona_config = state.get("persona_config", {})
    steps = list(state.get("thinking_log", []))

    client = VoicevoxClient()

    # Check engine availability
    if not client.is_available():
        print("      VOICEVOX engine not running — skipping audio stage")
        steps.append({
            "layer": "audio",
            "node": "synthesizer",
            "action": "skip",
            "reasoning": "VOICEVOX engine not available at http://localhost:50021",
        })
        return {"audio_metadata": [], "thinking_log": steps}

    audio_dir = run_dir / "06_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Narrator uses _default_a voice (or 0)
    narrator_id = _resolve_speaker_id("_narrator", persona_config)
    if narrator_id == 0:
        voice_map = persona_config.get("voice", {})
        narrator_id = int(voice_map.get("_default_a", 0))

    audio_metadata = []

    for script in scripts:
        if not isinstance(script, dict):
            continue

        ep_num = script.get("episode_number", 0)
        ep_label = f"ep{ep_num:02d}"
        ep_title = script.get("title", "")
        print(f"      Episode {ep_num}: {ep_title}")

        episode_audio = AudioSegment.empty()
        line_count = 0
        error_count = 0
        prev_speaker = None
        t0 = time.time()

        # Opening bridge
        opening = script.get("opening_bridge", "")
        if opening:
            seg = _synthesize_line(client, opening, narrator_id, speed_scale, intonation_scale)
            if seg:
                episode_audio += seg
                episode_audio += AudioSegment.silent(duration=SILENCE_SECTION_MS)
                line_count += 1
            else:
                error_count += 1

        # Dialogue
        for dl in script.get("dialogue", []):
            if isinstance(dl, dict):
                speaker = dl.get("speaker", "")
                line_text = dl.get("line", "")
            else:
                continue

            if not line_text.strip():
                continue

            speaker_id = _resolve_speaker_id(speaker, persona_config)

            # Insert silence based on speaker transition
            if prev_speaker is not None:
                if speaker == prev_speaker:
                    episode_audio += AudioSegment.silent(duration=SILENCE_SAME_SPEAKER_MS)
                else:
                    episode_audio += AudioSegment.silent(duration=SILENCE_SPEAKER_CHANGE_MS)

            seg = _synthesize_line(client, line_text, speaker_id, speed_scale, intonation_scale)
            if seg:
                episode_audio += seg
                line_count += 1
            else:
                error_count += 1

            prev_speaker = speaker

        # Closing hook
        closing = script.get("closing_hook", "")
        if closing:
            episode_audio += AudioSegment.silent(duration=SILENCE_SECTION_MS)
            seg = _synthesize_line(client, closing, narrator_id, speed_scale, intonation_scale)
            if seg:
                episode_audio += seg
                line_count += 1
            else:
                error_count += 1

        # Export to MP3
        elapsed = time.time() - t0
        duration_sec = len(episode_audio) / 1000.0

        if len(episode_audio) > 0:
            mp3_path = audio_dir / f"{ep_label}.mp3"
            episode_audio.export(str(mp3_path), format="mp3", bitrate=MP3_BITRATE)
            file_size = mp3_path.stat().st_size
            print(f"        -> {mp3_path.name}: {duration_sec:.1f}s, "
                  f"{file_size / 1024 / 1024:.1f}MB, {line_count} lines "
                  f"({error_count} errors) [{elapsed:.1f}s]")
        else:
            mp3_path = None
            file_size = 0
            print(f"        -> (no audio produced, {error_count} errors)")

        meta = {
            "episode_number": ep_num,
            "title": ep_title,
            "file": str(mp3_path) if mp3_path else None,
            "duration_sec": round(duration_sec, 1),
            "file_size_bytes": file_size,
            "lines_synthesized": line_count,
            "errors": error_count,
            "synthesis_time_sec": round(elapsed, 1),
        }
        audio_metadata.append(meta)

    steps.append({
        "layer": "audio",
        "node": "synthesizer",
        "action": "synthesize_all",
        "reasoning": f"Synthesized {len(audio_metadata)} episodes via VOICEVOX",
    })

    # Save metadata JSON alongside audio files
    meta_path = run_dir / "06_audio.json"
    meta_path.write_text(json.dumps(audio_metadata, ensure_ascii=False, indent=2))

    return {"audio_metadata": audio_metadata, "thinking_log": steps}


def format_audio_report(metadata: list[dict]) -> str:
    """Create a human-readable audio synthesis report."""
    lines = ["# Audio Synthesis Report", ""]

    if not metadata:
        lines.append("No audio files generated (VOICEVOX not available or no scripts).")
        return "\n".join(lines)

    total_duration = sum(m.get("duration_sec", 0) for m in metadata)
    total_size = sum(m.get("file_size_bytes", 0) for m in metadata)
    total_errors = sum(m.get("errors", 0) for m in metadata)

    lines.append(f"**Total episodes:** {len(metadata)}")
    lines.append(f"**Total duration:** {total_duration / 60:.1f} minutes")
    lines.append(f"**Total size:** {total_size / 1024 / 1024:.1f} MB")
    if total_errors:
        lines.append(f"**Total errors:** {total_errors}")
    lines.append("")

    for m in metadata:
        ep = m.get("episode_number", "?")
        title = m.get("title", "")
        dur = m.get("duration_sec", 0)
        size_mb = m.get("file_size_bytes", 0) / 1024 / 1024
        n_lines = m.get("lines_synthesized", 0)
        errors = m.get("errors", 0)
        synth_time = m.get("synthesis_time_sec", 0)

        lines.append(f"## Episode {ep}: {title}")
        lines.append(f"- Duration: {dur / 60:.1f} min ({dur:.0f}s)")
        lines.append(f"- Size: {size_mb:.1f} MB")
        lines.append(f"- Lines: {n_lines} synthesized, {errors} errors")
        lines.append(f"- Synthesis time: {synth_time:.0f}s")
        lines.append("")

    return "\n".join(lines)
