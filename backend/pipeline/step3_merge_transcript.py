"""
Step 3 — merge the two per-channel segment lists into one conversation.

step2 gives us two separate lists of segments (one for the agent channel,
one for the customer channel), each already timestamped in seconds relative
to the start of the call. Here we just interleave them by start time and
assign sequential segment IDs, so the result reads as an actual back-and-forth
conversation.

We also produce a plain-text "formatted" version of the same transcript,
labelled with segment IDs and MM:SS timestamps, for Sneha's AI analysis step
to read and cite evidence from directly, e.g.:

    [seg_1][00:02-00:06] AGENT: Thank you for calling...
    [seg_2][00:07-00:13] CUSTOMER: My card was charged twice...

Run directly for a self-contained demo (no API key or audio needed):
    venv\\Scripts\\python.exe backend\\pipeline\\step3_merge_transcript.py --demo

Or to merge two real segment-list JSON files (as saved by step2):
    venv\\Scripts\\python.exe backend\\pipeline\\step3_merge_transcript.py --agent-json a.json --customer-json c.json
"""

import argparse
import json
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    """Seconds -> MM:SS. Calls run well under an hour so we don't need HH:MM:SS."""
    total_seconds = int(round(seconds))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def merge_transcript(agent_segments: list[dict], customer_segments: list[dict]) -> dict:
    """
    Interleave agent + customer segments by start time and assign seg_N ids.

    Returns:
        {
            "segments": [{ "id": "seg_1", "speaker": ..., "start": ..., "end": ..., "text": ... }, ...],
            "formatted_text": "[seg_1][00:02-00:06] AGENT: ...\\n[seg_2]..."
        }
    """
    combined = list(agent_segments) + list(customer_segments)
    combined.sort(key=lambda seg: seg["start"])

    segments = []
    for i, seg in enumerate(combined, start=1):
        segments.append(
            {
                "id": f"seg_{i}",
                "speaker": seg["speaker"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
            }
        )

    lines = [
        f"[{seg['id']}][{format_timestamp(seg['start'])}-{format_timestamp(seg['end'])}] "
        f"{seg['speaker'].upper()}: {seg['text']}"
        for seg in segments
    ]

    return {"segments": segments, "formatted_text": "\n".join(lines)}


_DEMO_AGENT = [
    {"speaker": "agent", "start": 0.5, "end": 4.2, "text": "Thank you for calling, how can I help you today?"},
    {"speaker": "agent", "start": 14.0, "end": 19.5, "text": "I'm sorry to hear that, let me pull up your account."},
]
_DEMO_CUSTOMER = [
    {"speaker": "customer", "start": 5.0, "end": 12.8, "text": "Hi, my card was charged twice for the same transaction."},
    {"speaker": "customer", "start": 20.1, "end": 23.0, "text": "Okay, thank you."},
]


def _main() -> None:
    parser = argparse.ArgumentParser(description="Merge agent + customer segment lists into one transcript.")
    parser.add_argument("--agent-json", help="Path to a JSON file: list of agent segments from step2.")
    parser.add_argument("--customer-json", help="Path to a JSON file: list of customer segments from step2.")
    parser.add_argument("--demo", action="store_true", help="Run with built-in example segments instead of files.")
    args = parser.parse_args()

    if args.demo:
        agent_segments, customer_segments = _DEMO_AGENT, _DEMO_CUSTOMER
    elif args.agent_json and args.customer_json:
        agent_segments = json.loads(Path(args.agent_json).read_text())
        customer_segments = json.loads(Path(args.customer_json).read_text())
    else:
        parser.error("Pass either --demo, or both --agent-json and --customer-json.")
        return

    result = merge_transcript(agent_segments, customer_segments)

    print(f"{len(result['segments'])} merged segments:\n")
    print(result["formatted_text"])


if __name__ == "__main__":
    _main()
