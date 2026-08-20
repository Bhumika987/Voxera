"""
Step 1 — split a stereo call recording into two mono WAV files.

The recordings come in as a single stereo MP3:
    left channel  = agent
    right channel = customer

We split by channel (not diarization — the phone system already separated
the speakers for us) and write two mono WAVs to data/processed/. This keeps
each speaker's audio on its own timeline, with position 0 == the start of
the call, so timestamps we get back from transcription later line up
exactly with the original recording.

Run directly for a quick manual test:
    venv\\Scripts\\python.exe backend\\pipeline\\step1_split_audio.py --audio data\\audio\\<id>.mp3
"""

import argparse
import wave
from pathlib import Path

import ffmpeg
import imageio_ffmpeg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


class AudioSplitError(RuntimeError):
    """Raised when ffmpeg fails or a channel comes back empty/silent."""


def _run_channel_extract(input_path: Path, out_path: Path, channel_index: int) -> None:
    """Extract one channel (0=left/agent, 1=right/customer) as mono 8kHz WAV."""
    stream = ffmpeg.input(str(input_path))
    stream = ffmpeg.output(
        stream,
        str(out_path),
        **{
            "map_channel": f"0.0.{channel_index}",
            "ar": 8000,
            "ac": 1,
            "acodec": "pcm_s16le",
        },
    )
    stream = ffmpeg.overwrite_output(stream)
    try:
        ffmpeg.run(stream, cmd=FFMPEG_EXE, capture_stdout=True, capture_stderr=True, quiet=True)
    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else str(e)
        raise AudioSplitError(f"ffmpeg failed extracting channel {channel_index} from {input_path.name}: {stderr}") from e


def _get_duration_seconds(wav_path: Path) -> float:
    """
    Read duration directly from the WAV header.

    imageio_ffmpeg only bundles ffmpeg, not ffprobe, so we read the PCM WAV
    we just produced ourselves instead of shelling out again.
    """
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def split_audio(mp3_path: Path, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict:
    """
    Split one stereo call recording into agent/customer mono WAVs.

    Returns a dict:
        {
            "call_id": str,
            "agent_wav": Path,
            "customer_wav": Path,
            "agent_duration": float,   # seconds
            "customer_duration": float,
        }

    Raises AudioSplitError if ffmpeg fails, or if a channel comes back
    essentially empty (near-zero duration), which usually means the source
    file wasn't actually stereo or a channel was silent/missing.
    """
    mp3_path = Path(mp3_path)
    if not mp3_path.exists():
        raise AudioSplitError(f"Audio file not found: {mp3_path}")

    call_id = mp3_path.stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    agent_wav = output_dir / f"{call_id}_agent.wav"
    customer_wav = output_dir / f"{call_id}_customer.wav"

    _run_channel_extract(mp3_path, agent_wav, channel_index=0)  # left = agent
    _run_channel_extract(mp3_path, customer_wav, channel_index=1)  # right = customer

    agent_duration = _get_duration_seconds(agent_wav)
    customer_duration = _get_duration_seconds(customer_wav)

    if agent_duration < 0.5:
        raise AudioSplitError(f"{call_id}: agent channel is essentially empty ({agent_duration:.2f}s)")
    if customer_duration < 0.5:
        raise AudioSplitError(f"{call_id}: customer channel is essentially empty ({customer_duration:.2f}s)")

    return {
        "call_id": call_id,
        "agent_wav": agent_wav,
        "customer_wav": customer_wav,
        "agent_duration": agent_duration,
        "customer_duration": customer_duration,
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description="Split a stereo call MP3 into agent/customer WAVs.")
    parser.add_argument("--audio", required=True, help="Path to the source stereo MP3.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to write the two WAV files into (default: data/processed).",
    )
    args = parser.parse_args()

    result = split_audio(Path(args.audio), Path(args.output_dir))

    print(f"call_id:           {result['call_id']}")
    print(f"agent WAV:         {result['agent_wav']}  ({result['agent_duration']:.2f}s)")
    print(f"customer WAV:      {result['customer_wav']}  ({result['customer_duration']:.2f}s)")


if __name__ == "__main__":
    _main()
