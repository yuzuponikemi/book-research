"""VOICEVOX Engine HTTP client for text-to-speech synthesis."""

import argparse
import sys

import httpx


class VoicevoxClient:
    """Client for VOICEVOX Engine REST API (localhost:50021)."""

    def __init__(self, host: str = "http://localhost:50021", timeout: float = 90.0):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        """Check if the VOICEVOX engine is running."""
        try:
            resp = httpx.get(f"{self.host}/version", timeout=5.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def get_speakers(self) -> list[dict]:
        """Get list of available speakers."""
        resp = httpx.get(f"{self.host}/speakers", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def audio_query(self, text: str, speaker_id: int) -> dict:
        """Create an audio synthesis query from text."""
        resp = httpx.post(
            f"{self.host}/audio_query",
            params={"text": text, "speaker": speaker_id},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def synthesis(self, query: dict, speaker_id: int) -> bytes:
        """Synthesize WAV audio from an audio query."""
        resp = httpx.post(
            f"{self.host}/synthesis",
            params={"speaker": speaker_id},
            json=query,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.content

    def synthesize(self, text: str, speaker_id: int) -> bytes:
        """Convenience method: text -> WAV bytes (audio_query + synthesis)."""
        query = self.audio_query(text, speaker_id)
        return self.synthesis(query, speaker_id)


def main():
    """CLI test: python3 -m src.audio.voicevox_client "テスト" --speaker 0"""
    parser = argparse.ArgumentParser(description="VOICEVOX client test")
    parser.add_argument("text", help="Text to synthesize")
    parser.add_argument("--speaker", type=int, default=0, help="Speaker ID (default: 0)")
    parser.add_argument("--output", default="test_output.wav", help="Output WAV file")
    parser.add_argument("--list-speakers", action="store_true", help="List available speakers")
    args = parser.parse_args()

    client = VoicevoxClient()

    if not client.is_available():
        print("Error: VOICEVOX engine is not running at http://localhost:50021")
        print("Start it with: open -a VOICEVOX (or run the engine binary)")
        sys.exit(1)

    if args.list_speakers:
        speakers = client.get_speakers()
        for speaker in speakers:
            print(f"\n{speaker['name']}:")
            for style in speaker.get("styles", []):
                print(f"  ID {style['id']}: {style['name']}")
        return

    print(f"Synthesizing: '{args.text}' (speaker={args.speaker})")
    wav_data = client.synthesize(args.text, args.speaker)
    with open(args.output, "wb") as f:
        f.write(wav_data)
    print(f"Saved: {args.output} ({len(wav_data)} bytes)")


if __name__ == "__main__":
    main()
