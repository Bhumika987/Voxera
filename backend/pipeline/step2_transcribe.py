"""
Step 2 — turn one mono WAV (agent or customer channel) into timed text segments.

We call this once per channel file (not once per call — the channels were
already split apart in step 1). Since step 1 preserved the original call
timeline when it split channels, second 0 of the WAV is still second 0 of
the call, so these timestamps line up with the recording.

Three-layer fallback so a demo never fails outright, tried in order:
    1. AssemblyAI       — best quality, needs internet + ASSEMBLYAI_API_KEY
    2. Groq Whisper API — whisper-large-v3-turbo, needs internet + GROQ_API_KEY
    3. faster-whisper    — fully local/offline, no API key, always succeeds

Each layer is tried once (no per-layer retry loop) — if one fails for any
reason, we move to the next immediately rather than spend time retrying a
single flaky provider. Resilience here comes from having three independent
providers, not from hammering one of them.

Run directly for a quick manual test:
    venv\\Scripts\\python.exe backend\\pipeline\\step2_transcribe.py --wav data\\processed\\<id>_agent.wav --speaker agent
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Literal

import assemblyai as aai
import groq
from dotenv import load_dotenv

# Windows consoles often default to cp1252, which can't encode the emoji in
# the fallback-status prints below (UnicodeEncodeError would crash the whole
# batch mid-run over a log message). Force UTF-8 on stdout defensively;
# harmless if it's already UTF-8, and if a stream genuinely can't be
# reconfigured (e.g. some captured test stream), just proceed without it.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
if ASSEMBLYAI_API_KEY:
    aai.settings.api_key = ASSEMBLYAI_API_KEY

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"
LOCAL_WHISPER_MODEL = "tiny"

Speaker = Literal["agent", "customer"]


class TranscriptionError(RuntimeError):
    """Raised only if all three fallback layers fail (local whisper should make this rare)."""


_groq_client: groq.Groq | None = None


def _get_groq_client() -> groq.Groq:
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise TranscriptionError("GROQ_API_KEY is not set.")
        _groq_client = groq.Groq(api_key=GROQ_API_KEY)
    return _groq_client


_local_model = None


def get_local_model():
    """Loads the local faster-whisper model once and reuses it — loading it
    per call would be expensive (model weights + CPU inference engine init)."""
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel

        print(f"  (loading local faster-whisper model '{LOCAL_WHISPER_MODEL}', first use only...)")
        _local_model = WhisperModel(LOCAL_WHISPER_MODEL, device="cpu", compute_type="int8")
    return _local_model


def transcribe_assemblyai(audio_path: Path, speaker_label: Speaker) -> list[dict]:
    """Layer 1: AssemblyAI. Best quality, needs internet + a valid API key."""
    if not ASSEMBLYAI_API_KEY:
        raise TranscriptionError("ASSEMBLYAI_API_KEY is not set.")

    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(str(audio_path))

    if transcript.status == aai.TranscriptStatus.error:
        raise TranscriptionError(f"AssemblyAI returned an error: {transcript.error}")

    return [
        {
            "speaker": speaker_label,
            "start": round(s.start / 1000.0, 2),
            "end": round(s.end / 1000.0, 2),
            "text": s.text.strip(),
        }
        for s in transcript.get_sentences()
        if s.text and s.text.strip()
    ]


def transcribe_groq(audio_path: Path, speaker_label: Speaker) -> list[dict]:
    """Layer 2: Groq's hosted Whisper API. Free, needs internet + a valid GROQ_API_KEY."""
    client = _get_groq_client()
    audio_path = Path(audio_path)

    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(audio_path.name, f.read()),
            model=GROQ_WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            language="en",
        )

    segments = getattr(transcription, "segments", None) or []
    return [
        {
            "speaker": speaker_label,
            "start": round(seg["start"] if isinstance(seg, dict) else seg.start, 2),
            "end": round(seg["end"] if isinstance(seg, dict) else seg.end, 2),
            "text": (seg["text"] if isinstance(seg, dict) else seg.text).strip(),
        }
        for seg in segments
        if (seg["text"] if isinstance(seg, dict) else seg.text).strip()
    ]


def transcribe_local(audio_path: Path, speaker_label: Speaker) -> list[dict]:
    """Layer 3: faster-whisper, fully offline. No API key, no internet — always succeeds."""
    model = get_local_model()
    segments, _info = model.transcribe(str(audio_path), language="en", vad_filter=True)

    result = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            result.append(
                {
                    "speaker": speaker_label,
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": text,
                }
            )
    return result


def transcribe_audio(audio_path: Path, speaker_label: Speaker) -> tuple[list[dict], str]:
    """
    Transcribe one mono audio file, trying AssemblyAI -> Groq Whisper -> local
    faster-whisper in order until one succeeds. Always returns a result (the
    local layer has no external dependency, so it never fails) — never raises
    unless something is fundamentally wrong (e.g. the file itself is missing).

    Returns (segments, provider) where provider is "assemblyai" | "groq_whisper"
    | "local_whisper" — lets callers record which one actually handled this
    channel (see process_one_call.py's transcription_provider field).

    Segment format (same for all three providers):
        [{ "speaker": "agent"|"customer", "start": float, "end": float, "text": str }, ...]
    start/end are in seconds, relative to the start of this file.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    try:
        result = transcribe_assemblyai(audio_path, speaker_label)
        if result:
            print("  ✅ AssemblyAI succeeded")
            return result, "assemblyai"
    except Exception as e:  # noqa: BLE001 - any failure here should fall through, not crash
        print(f"  ⚠️ AssemblyAI failed: {e}")
        print("  → trying Groq Whisper...")

    try:
        result = transcribe_groq(audio_path, speaker_label)
        if result:
            print("  ✅ Groq Whisper succeeded")
            return result, "groq_whisper"
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ Groq failed: {e}")
        print("  → using local faster-whisper...")

    result = transcribe_local(audio_path, speaker_label)
    print("  ✅ Local Whisper succeeded (offline)")
    return result, "local_whisper"


def transcribe_wav(wav_path: Path, speaker: Speaker) -> tuple[list[dict], str]:
    """Kept as the stable entry point process_one_call.py depends on — delegates
    to transcribe_audio's 3-layer fallback."""
    return transcribe_audio(wav_path, speaker)


async def transcribe_wav_async(wav_path: Path, speaker: Speaker) -> tuple[list[dict], str]:
    """Async wrapper around transcribe_wav — runs the blocking call in a worker thread."""
    return await asyncio.to_thread(transcribe_wav, wav_path, speaker)


async def transcribe_many(
    jobs: list[tuple[Path, Speaker]],
    max_concurrency: int = 20,
) -> list[tuple[list[dict], str] | TranscriptionError]:
    """
    Transcribe many audio files concurrently, capped at max_concurrency in flight at once.

    `jobs` is a list of (path, speaker) pairs. Returns (segments, provider)
    results in the same order as `jobs`; a job that failed all three layers
    (extremely unlikely) yields the TranscriptionError instance instead of
    raising, so one bad file doesn't take down the whole batch.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run(wav_path: Path, speaker: Speaker):
        async with semaphore:
            try:
                return await transcribe_wav_async(wav_path, speaker)
            except TranscriptionError as e:
                return e

    return await asyncio.gather(*(_run(wav_path, speaker) for wav_path, speaker in jobs))


def _main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe one audio channel (AssemblyAI -> Groq -> local fallback).")
    parser.add_argument("--wav", required=True, help="Path to the mono WAV file.")
    parser.add_argument("--speaker", required=True, choices=["agent", "customer"])
    args = parser.parse_args()

    print(f"Transcribing {args.wav} as {args.speaker}...")
    segments, provider = transcribe_wav(Path(args.wav), args.speaker)

    print(f"\nProvider: {provider}")
    print(f"{len(segments)} segments:")
    for seg in segments:
        print(f"  [{seg['start']:>6.2f}-{seg['end']:>6.2f}] {seg['speaker'].upper()}: {seg['text']}")


if __name__ == "__main__":
    _main()
