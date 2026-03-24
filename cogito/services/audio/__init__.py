"""Audio synthesis service: Japanese scripts → MP3 via VOICEVOX."""
from cogito.services.audio.synthesizer import synthesize_audio, format_audio_report
from cogito.services.audio.voicevox_client import VoicevoxClient

__all__ = ["synthesize_audio", "format_audio_report", "VoicevoxClient"]
