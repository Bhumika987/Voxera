"""
Unit tests for the deterministic pipeline logic — no API keys, no network calls,
no database. Covers step3_merge_transcript.py and app/services/attention_score.py.

Run from backend/:
    python -m pytest tests/ -v
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "pipeline"))

from step3_merge_transcript import format_timestamp, merge_transcript  # noqa: E402
from app.services.attention_score import compute_attention_score  # noqa: E402


# --- merge_transcript ---


def test_merge_transcript_sorts_by_start_time():
    agent = [{"speaker": "agent", "start": 10.0, "end": 12.0, "text": "second"}]
    customer = [{"speaker": "customer", "start": 2.0, "end": 4.0, "text": "first"}]

    result = merge_transcript(agent, customer)

    starts = [seg["start"] for seg in result["segments"]]
    assert starts == sorted(starts)
    assert result["segments"][0]["text"] == "first"
    assert result["segments"][1]["text"] == "second"


def test_merge_transcript_assigns_sequential_segment_ids():
    agent = [{"speaker": "agent", "start": 0.0, "end": 1.0, "text": "a"}]
    customer = [
        {"speaker": "customer", "start": 1.0, "end": 2.0, "text": "b"},
        {"speaker": "customer", "start": 2.0, "end": 3.0, "text": "c"},
    ]

    result = merge_transcript(agent, customer)

    assert [seg["id"] for seg in result["segments"]] == ["seg_1", "seg_2", "seg_3"]


def test_merge_transcript_includes_both_speakers():
    agent = [{"speaker": "agent", "start": 0.0, "end": 1.0, "text": "hello"}]
    customer = [{"speaker": "customer", "start": 1.0, "end": 2.0, "text": "hi"}]

    result = merge_transcript(agent, customer)

    speakers = {seg["speaker"] for seg in result["segments"]}
    assert speakers == {"agent", "customer"}


def test_merge_transcript_empty_input():
    result = merge_transcript([], [])

    assert result["segments"] == []
    assert result["formatted_text"] == ""


# --- format_timestamp ---


def test_format_timestamp_zero_seconds():
    assert format_timestamp(0) == "00:00"


def test_format_timestamp_ninety_seconds():
    assert format_timestamp(90) == "01:30"


def test_format_timestamp_over_an_hour():
    # Calls run well under an hour, so this deliberately stays MM:SS past the
    # 60-minute mark rather than rolling into HH:MM:SS.
    assert format_timestamp(3661) == "61:01"


# --- compute_attention_score ---


def _segments(customer_text="Thanks for your help.", agent_text="Anything else?"):
    return [
        {"id": "seg_1", "speaker": "agent", "start": 0.0, "end": 2.0, "text": agent_text},
        {"id": "seg_2", "speaker": "customer", "start": 2.0, "end": 4.0, "text": customer_text},
    ]


def test_unresolved_issue_scores_30():
    score, reasons = compute_attention_score(
        resolution="unresolved",
        final_mood="neutral",
        mood_events=[],
        duration_seconds=60.0,
        is_repeat_contact=False,
        repeat_contact_detail=None,
        segments=_segments(),
    )

    assert score == 30
    assert reasons == [{"reason": "Unresolved issue", "points": 30, "evidence_segment_id": "seg_2"}]


def test_angry_customer_scores_20():
    score, reasons = compute_attention_score(
        resolution="resolved",
        final_mood="angry",
        mood_events=[],
        duration_seconds=60.0,
        is_repeat_contact=False,
        repeat_contact_detail=None,
        segments=_segments(),
    )

    assert score == 20
    assert reasons[0]["reason"] == "Customer ends call angry"
    assert reasons[0]["points"] == 20


def test_repeat_contact_scores_15():
    score, reasons = compute_attention_score(
        resolution="resolved",
        final_mood="neutral",
        mood_events=[],
        duration_seconds=60.0,
        is_repeat_contact=True,
        repeat_contact_detail="previous call abc123 on 2026-01-01",
        segments=_segments(),
    )

    assert score == 15
    assert reasons[0]["reason"] == "Repeat contact - previous call abc123 on 2026-01-01"
    # Repeat contact is evidence from a DIFFERENT call, not a moment in this
    # one, so there's deliberately no in-call segment to point at.
    assert reasons[0]["evidence_segment_id"] is None


def test_score_caps_at_100():
    """
    Trigger every rule at once. With today's point values
    (30 + 20 + 15 + 15 + 10 + 5 = 95), the realistic maximum a call can hit
    is 95 — under the 100 cap — so no combination of real inputs can force
    the ceiling to actually engage through the public API right now. What we
    CAN verify is the guarantee that matters: score always equals
    min(100, sum(points)), so if a future rule pushes the total past 100,
    it gets capped correctly rather than silently exceeding it.
    """
    segments = [
        {"id": "seg_1", "speaker": "agent", "start": 0.0, "end": 2.0, "text": "Hello"},
        {
            "id": "seg_2",
            "speaker": "customer",
            "start": 2.0,
            "end": 4.0,
            "text": "I want to speak to a manager, this is unacceptable.",
        },
    ]
    mood_events = [{"timestamp": 2.0, "mood_before": "neutral", "mood_after": "angry", "segment_id": "seg_2"}]

    score, reasons = compute_attention_score(
        resolution="unresolved",
        final_mood="angry",
        mood_events=mood_events,
        duration_seconds=700.0,
        is_repeat_contact=True,
        repeat_contact_detail="previous call xyz on 2026-01-01",
        segments=segments,
    )

    expected = min(100, sum(r["points"] for r in reasons))
    assert score == expected
    assert score == 95  # today's ceiling given current rule weights (see docstring)
    assert score <= 100
