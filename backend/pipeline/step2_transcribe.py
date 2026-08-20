"""
Step 2 — turn one mono WAV (agent or customer channel) into timed text segments.

We call AssemblyAI once per channel file (not once per call — the channels
were already split apart in step 1). AssemblyAI's sentence-boundary
detection gives us natural conversation turns, each with a start/end time
in milliseconds relative to that WAV file. Since step 1 preserved the
original call timeline when it split channels, second 0 of the WAV is
still second 0 of the call, so these timestamps line up with the recording.

Run directly for a quick manual test:
    venv\\Scripts\\python.exe backend\\pipeline\\step2_transcribe.py --wav data\\processed\\<id>_agent.wav --speaker agent
"""

import argparse
import asyncio
import os
import time
from pathlib import Path
from typing import Literal

import assemblyai as aai
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
if API_KEY:
    aai.settings.api_key = API_KEY

Speaker = Literal["agent", "customer"]

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3  # doubles each retry: 3s, 6s, 12s


class TranscriptionError(RuntimeError):
    """Raised when a channel fails to transcribe after all retries."""


def _require_api_key() -> None:
    if not API_KEY:
        raise TranscriptionError(
            "ASSEMBLYAI_API_KEY is not set. Create backend/.env (see backend/.env.example) "
            "with your AssemblyAI key."
        )


def transcribe_wav(wav_path: Path, speaker: Speaker) -> list[dict]:
    """
    Transcribe one mono WAV file synchronously (blocks until AssemblyAI finishes).

    Returns a list of segments, sentence-by-sentence:
        [{ "speaker": "agent"|"customer", "start": float, "end": float, "text": str }]
    start/end are in seconds, relative to the start of this WAV (== start of the call).

    Retries transient failures (network errors, AssemblyAI-side transcription
    errors) up to MAX_RETRIES times with exponential backoff. Raises
    TranscriptionError if all attempts fail — callers should catch this,
    log it, and skip the call rather than crash a batch run.
    """
    _require_api_key()
    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise TranscriptionError(f"WAV file not found: {wav_path}")

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            transcriber = aai.Transcriber()
            transcript = transcriber.transcribe(str(wav_path))

            if transcript.status == aai.TranscriptStatus.error:
                raise TranscriptionError(f"AssemblyAI returned an error for {wav_path.name}: {transcript.error}")

            sentences = transcript.get_sentences()
            segments = [
                {
                    "speaker": speaker,
                    "start": round(s.start / 1000.0, 2),
                    "end": round(s.end / 1000.0, 2),
                    "text": s.text.strip(),
                }
                for s in sentences
                if s.text and s.text.strip()
            ]
            return segments

        except Exception as e:  # noqa: BLE001 - deliberately broad, we retry any failure
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(f"  [retry {attempt}/{MAX_RETRIES}] {wav_path.name} failed ({e}); retrying in {wait}s...")
                time.sleep(wait)

    raise TranscriptionError(f"Giving up on {wav_path.name} after {MAX_RETRIES} attempts: {last_error}") from last_error


async def transcribe_wav_async(wav_path: Path, speaker: Speaker) -> list[dict]:
    """Async wrapper around transcribe_wav — runs the blocking SDK call in a worker thread."""
    return await asyncio.to_thread(transcribe_wav, wav_path, speaker)


async def transcribe_many(
    jobs: list[tuple[Path, Speaker]],
    max_concurrency: int = 20,
) -> list[list[dict] | TranscriptionError]:
    """
    Transcribe many WAV files concurrently, capped at max_concurrency in flight at once.

    `jobs` is a list of (wav_path, speaker) pairs. Returns results in the same
    order as `jobs`; a job that failed all its retries yields the
    TranscriptionError instance instead of raising, so one bad file doesn't
    take down the whole batch.
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
    parser = argparse.ArgumentParser(description="Transcribe one WAV channel with AssemblyAI.")
    parser.add_argument("--wav", required=True, help="Path to the mono WAV file.")
    parser.add_argument("--speaker", required=True, choices=["agent", "customer"])
    args = parser.parse_args()

    print(f"Transcribing {args.wav} as {args.speaker}... (this calls the AssemblyAI API and can take ~10-30s)")
    segments = transcribe_wav(Path(args.wav), args.speaker)

    print(f"\n{len(segments)} segments:")
    for seg in segments:
        print(f"  [{seg['start']:>6.2f}-{seg['end']:>6.2f}] {seg['speaker'].upper()}: {seg['text']}")


if __name__ == "__main__":
    _main()
