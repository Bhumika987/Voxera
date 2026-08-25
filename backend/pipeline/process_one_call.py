"""
Step 4 — full pipeline for ONE call, end to end.

audio + metadata --(step1)--> agent.wav, customer.wav
                  --(step2)--> agent segments, customer segments  [AssemblyAI]
                  --(step3)--> merged transcript
                  --(analyze_call)--> intent / mood / resolution / summary
                  --(attention_score)--> deterministic needs-attention score
                  --> saved to SQLite

Idempotent: if the call is already in the database with processed=True, this
returns immediately without re-transcribing (re-running the batch is safe).
If a call exists but was left half-processed (e.g. a crash mid-run), its
stale row and any partial child rows are deleted and it's reprocessed
from scratch.

Run directly:
    venv\\Scripts\\python.exe backend\\pipeline\\process_one_call.py --audio data\\audio\\<id>.mp3 --metadata data\\metadata\\<id>.json
"""

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))  # so `app.*` imports work when run as a plain script

from step1_split_audio import AudioSplitError, split_audio  # noqa: E402
from step2_transcribe import TranscriptionError, transcribe_wav, transcribe_wav_async  # noqa: E402
from step3_merge_transcript import merge_transcript  # noqa: E402
from metadata_utils import MetadataError, parse_metadata  # noqa: E402

from app.database.schema import (  # noqa: E402
    AttentionReason,
    Agent,
    Call,
    Customer,
    MoodEvent,
    TranscriptSegment,
    Session,
    get_session,
    init_db,
)
from app.services.analyze import AnalysisError, ModelUnavailableError, analyze_call  # noqa: E402
from app.services.attention_score import compute_attention_score  # noqa: E402
from app.services.chroma import add_call_to_chroma  # noqa: E402


class CallProcessingError(RuntimeError):
    pass


def _get_or_create_customer(session: Session, name: str) -> Customer:
    customer = session.query(Customer).filter_by(name=name).one_or_none()
    if customer is None:
        customer = Customer(name=name)
        session.add(customer)
        session.flush()  # assigns customer.id without committing
    return customer


def _get_or_create_agent(session: Session, name: str) -> Agent:
    agent = session.query(Agent).filter_by(name=name).one_or_none()
    if agent is None:
        agent = Agent(name=name)
        session.add(agent)
        session.flush()
    return agent


def _check_repeat_contact(session: Session, customer_id: int) -> tuple[bool, str | None]:
    """True if this customer has at least one earlier call already stored."""
    prior = (
        session.query(Call)
        .filter(Call.customer_id == customer_id)
        .order_by(Call.started_at.desc())
        .first()
    )
    if prior is None:
        return False, None
    return True, f"previous call {prior.id} on {prior.started_at.date()}"


def _save_call(
    session: Session, call_id: str, meta: dict, audio_path: Path, merged: dict, transcription_provider: str
) -> None:
    """Runs analysis + deterministic scoring on an already-merged transcript (see
    step3_merge_transcript.merge_transcript) and writes everything for one call.
    Shared by both the sync and async pipelines below."""
    segments = merged["segments"]
    analysis = analyze_call(merged["formatted_text"], segments)

    customer = _get_or_create_customer(session, meta["customer_name"])
    agent = _get_or_create_agent(session, meta["agent_name"])
    is_repeat, repeat_detail = _check_repeat_contact(session, customer.id)

    score, reasons = compute_attention_score(
        resolution=analysis["resolution"],
        final_mood=analysis["final_mood"],
        mood_events=analysis["mood_events"],
        duration_seconds=meta["duration_seconds"],
        is_repeat_contact=is_repeat,
        repeat_contact_detail=repeat_detail,
        segments=segments,
    )

    call = Call(
        id=call_id,
        customer_id=customer.id,
        agent_id=agent.id,
        started_at=meta["started_at"],
        duration_seconds=meta["duration_seconds"],
        audio_path=str(audio_path),
        intent=analysis["intent"],
        intent_evidence_segment_id=analysis["intent_evidence_segment_id"],
        resolution=analysis["resolution"],
        summary=analysis["summary"],
        initial_mood=analysis["initial_mood"],
        final_mood=analysis["final_mood"],
        mood_shift_time=analysis["mood_shift_time"],
        mood_shift_segment_id=analysis["mood_shift_segment_id"],
        attention_score=score,
        model_used=analysis["model_used"],
        transcription_provider=transcription_provider,
        processed=True,
    )
    session.add(call)
    session.flush()

    for seg in segments:
        session.add(
            TranscriptSegment(
                call_id=call_id,
                segment_id=seg["id"],
                speaker=seg["speaker"],
                start_time=seg["start"],
                end_time=seg["end"],
                text=seg["text"],
            )
        )

    for reason in reasons:
        session.add(
            AttentionReason(
                call_id=call_id,
                reason=reason["reason"],
                points=reason["points"],
                evidence_segment_id=reason["evidence_segment_id"],
            )
        )

    for mood_event in analysis["mood_events"]:
        session.add(
            MoodEvent(
                call_id=call_id,
                timestamp=mood_event["timestamp"],
                mood_before=mood_event["mood_before"],
                mood_after=mood_event["mood_after"],
                segment_id=mood_event["segment_id"],
            )
        )

    session.commit()

    # Best-effort: the call is already durably saved above, so a search-index
    # hiccup here shouldn't fail the whole pipeline run.
    try:
        add_call_to_chroma(
            call_id=call_id,
            summary=analysis["summary"],
            metadata={
                "call_id": call_id,
                "customer_name": customer.name,
                "agent_name": agent.name,
                "intent": analysis["intent"],
                "resolution": analysis["resolution"],
                "attention_score": score,
                "initial_mood": analysis["initial_mood"],
                "final_mood": analysis["final_mood"],
                "duration_seconds": meta["duration_seconds"],
            },
        )
    except Exception as e:
        print(f"  [warning] failed to add call {call_id} to ChromaDB search index: {e}")


def _check_already_processed(session: Session, call_id: str) -> bool:
    """Returns True if this call is fully processed already. Deletes any stale
    half-processed row (e.g. left over from a crash) so it gets redone from scratch."""
    existing = session.get(Call, call_id)
    if existing is None:
        return False
    if existing.processed:
        return True
    session.delete(existing)
    session.flush()
    return False


def process_one_call(audio_path: Path, metadata_path: Path, session: Session | None = None) -> str:
    """Runs the full pipeline for one call, synchronously (agent then customer, in turn).
    Used by the single-call CLI. Returns the call_id. Reuses `session` if given
    (used by batch_process.py); otherwise opens and closes its own."""
    own_session = session is None
    if own_session:
        session = get_session()

    try:
        meta = parse_metadata(metadata_path)
        call_id = meta["call_id"]

        if _check_already_processed(session, call_id):
            return call_id  # already done — do NOT re-transcribe

        split_result = split_audio(audio_path)
        agent_segments, agent_provider = transcribe_wav(split_result["agent_wav"], "agent")
        customer_segments, customer_provider = transcribe_wav(split_result["customer_wav"], "customer")
        merged = merge_transcript(agent_segments, customer_segments)
        transcription_provider = f"agent={agent_provider},customer={customer_provider}"

        _save_call(session, call_id, meta, audio_path, merged, transcription_provider)
        return call_id

    except ModelUnavailableError:
        # Not a per-call failure — a config problem that will repeat
        # identically for every remaining call. Let it propagate unwrapped
        # so batch_process.py can stop the whole run instead of logging it
        # 1400+ times.
        session.rollback()
        raise
    except (AudioSplitError, TranscriptionError, MetadataError, AnalysisError) as e:
        session.rollback()
        raise CallProcessingError(str(e)) from e
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


async def process_one_call_async(audio_path: Path, metadata_path: Path) -> str:
    """Same pipeline as process_one_call, but the agent and customer channels are
    transcribed concurrently (not one after the other). Used by batch_process.py,
    which also runs many calls like this one concurrently at the same time — so a
    call in flight here means 2 concurrent AssemblyAI requests, not 1. Always opens
    and closes its own session (SQLAlchemy sessions aren't safe to share across
    concurrent tasks)."""
    session = get_session()
    try:
        meta = parse_metadata(metadata_path)
        call_id = meta["call_id"]

        if _check_already_processed(session, call_id):
            return call_id

        split_result = await asyncio.to_thread(split_audio, audio_path)
        (agent_segments, agent_provider), (customer_segments, customer_provider) = await asyncio.gather(
            transcribe_wav_async(split_result["agent_wav"], "agent"),
            transcribe_wav_async(split_result["customer_wav"], "customer"),
        )
        merged = merge_transcript(agent_segments, customer_segments)
        transcription_provider = f"agent={agent_provider},customer={customer_provider}"

        _save_call(session, call_id, meta, audio_path, merged, transcription_provider)
        return call_id

    except ModelUnavailableError:
        session.rollback()
        raise
    except (AudioSplitError, TranscriptionError, MetadataError, AnalysisError) as e:
        session.rollback()
        raise CallProcessingError(str(e)) from e
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Run the full pipeline for one call.")
    parser.add_argument("--audio", required=True, help="Path to the call's mp3.")
    parser.add_argument("--metadata", required=True, help="Path to the call's metadata json.")
    args = parser.parse_args()

    init_db()
    try:
        call_id = process_one_call(Path(args.audio), Path(args.metadata))
    except CallProcessingError as e:
        print(f"Failed: {e}")
        sys.exit(1)
    print(f"Processed call {call_id} - see data/vexora.db")


if __name__ == "__main__":
    _main()
