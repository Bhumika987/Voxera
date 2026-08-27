"""
One-time backfill: for each existing call, ask the model which transcript
segment proves the already-known resolution status, and store it as
resolution_evidence_segment_id.

Sends the reconstructed full transcript (built from transcript_segments,
byte-identical to what analyze_call() originally saw) but asks only a single
narrow question — not a full re-analysis. Uses backend/scripts/
_backfill_common.py's Groq 20b -> Ollama chain (never 120b).

Every returned segment id is validated against this call's own segments via
analyze.py's _validate_segment_id before being written — same
anti-hallucination guarantee as every other evidence field in this project.

Resumable by construction: the driving query only selects rows where
resolution_evidence_segment_id is still NULL.

Run directly:
    venv\\Scripts\\python.exe backend\\scripts\\backfill_resolution_evidence.py --limit 5
    venv\\Scripts\\python.exe backend\\scripts\\backfill_resolution_evidence.py
    venv\\Scripts\\python.exe backend\\scripts\\backfill_resolution_evidence.py --concurrency 5
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "pipeline"))

from sqlalchemy import text  # noqa: E402

from _backfill_common import ask  # noqa: E402
from app.database.schema import engine  # noqa: E402
from app.services.analyze import _validate_segment_id  # noqa: E402
from step3_merge_transcript import format_timestamp  # noqa: E402


def _reconstruct_transcript(conn, call_id: str) -> tuple[str, set[str]]:
    rows = conn.execute(
        text(
            "SELECT segment_id, speaker, start_time, end_time, text "
            "FROM transcript_segments WHERE call_id = :call_id ORDER BY start_time"
        ),
        {"call_id": call_id},
    ).fetchall()

    lines = [
        f"[{seg_id}][{format_timestamp(start)}-{format_timestamp(end)}] {speaker.upper()}: {seg_text}"
        for seg_id, speaker, start, end, seg_text in rows
    ]
    valid_ids = {row[0] for row in rows}
    return "\n".join(lines), valid_ids


def _system_prompt(resolution: str) -> str:
    return (
        "You are given a bank customer support call transcript and its already-determined "
        "resolution status. Find the ONE segment id that best proves this resolution status.\n\n"
        f'Resolution status: "{resolution}"\n\n'
        "Rules:\n"
        '- Respond with ONLY a single JSON object, no markdown, no commentary: {"segment_id": "<segment id>" or null}\n'
        "- The segment id must actually appear in the transcript below.\n"
        '- If the status is "unknown" or no single segment clearly proves it, respond {"segment_id": null}.'
    )


def _extract_segment_id(raw: str) -> str | None:
    text_ = raw.strip()
    if text_.startswith("```"):
        text_ = text_.split("\n", 1)[1] if "\n" in text_ else text_
        if text_.endswith("```"):
            text_ = text_[:-3]
        if text_.startswith("json"):
            text_ = text_[4:]
    text_ = text_.strip()
    try:
        parsed = json.loads(text_)
    except json.JSONDecodeError:
        return None
    return parsed.get("segment_id")


async def _process_one(
    semaphore: asyncio.Semaphore, call_id: str, resolution: str, ollama_only: bool
) -> tuple[str, str | None, str]:
    async with semaphore:
        with engine.connect() as conn:
            formatted_text, valid_ids = _reconstruct_transcript(conn, call_id)

        system_prompt = _system_prompt(resolution)
        user_prompt = f"Transcript:\n\n{formatted_text}"
        raw, model_used = await asyncio.to_thread(ask, system_prompt, user_prompt, 1500, ollama_only)

        raw_segment_id = _extract_segment_id(raw)
        segment_id = _validate_segment_id(raw_segment_id, valid_ids)
        return call_id, segment_id, model_used


async def _run(rows: list[tuple[str, str]], concurrency: int, show_text: bool, ollama_only: bool) -> None:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [_process_one(semaphore, call_id, resolution, ollama_only) for call_id, resolution in rows]

    completed = 0
    for coro in asyncio.as_completed(tasks):
        call_id, segment_id, model_used = await coro
        completed += 1

        with engine.connect() as conn:
            conn.execute(
                text("UPDATE calls SET resolution_evidence_segment_id = :seg WHERE id = :id"),
                {"seg": segment_id, "id": call_id},
            )
            conn.commit()

            evidence_text = None
            if show_text and segment_id is not None:
                row = conn.execute(
                    text("SELECT text FROM transcript_segments WHERE call_id = :call_id AND segment_id = :seg"),
                    {"call_id": call_id, "seg": segment_id},
                ).fetchone()
                evidence_text = row[0] if row else None

        resolution = dict(rows)[call_id]
        print(f"  [{completed}/{len(rows)}] {call_id} (resolution={resolution}): segment_id={segment_id!r} ({model_used})")
        if show_text and evidence_text is not None:
            print(f"      -> {evidence_text!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill calls.resolution_evidence_segment_id.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N rows (by id).")
    parser.add_argument("--concurrency", type=int, default=1, help="Calls to process at once.")
    parser.add_argument(
        "--ollama-only", action="store_true", help="Skip Groq entirely and use local Ollama for every call."
    )
    args = parser.parse_args()

    with engine.connect() as conn:
        query = (
            "SELECT id, resolution FROM calls "
            "WHERE resolution_evidence_segment_id IS NULL AND resolution IS NOT NULL ORDER BY id"
        )
        if args.limit is not None:
            query += f" LIMIT {args.limit}"
        rows = conn.execute(text(query)).fetchall()

    if not rows:
        print("Nothing to do — every considered row already has resolution_evidence_segment_id.")
        return

    print(f"Finding resolution evidence for {len(rows)} call(s)...")
    show_text = args.limit is not None
    asyncio.run(_run(rows, args.concurrency, show_text, args.ollama_only))
    print(f"\nDone. Processed {len(rows)} row(s).")


if __name__ == "__main__":
    main()
