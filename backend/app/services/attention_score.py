"""
Deterministic "needs a manager's attention today" score — NOT an AI judgment.

Every rule here is a plain if-check over facts we already have (AI-derived
fields like resolution/mood, or pipeline-only facts like call duration and
customer call history), so the score is reproducible and auditable. Each
triggered rule records which segment (if any) backs it up, per the project's
"every judgment must cite the moment that justifies it" requirement.

Rules (capped at 100 total):
    Unresolved issue              +30
    Customer ends angry           +20
    Major mood shift to negative  +15
    Repeat contact detected       +15
    Manager requested             +10
    Call over 10 minutes          +5

Two rules aren't tied to a single transcript moment by nature:
  - "Repeat contact" is evidence from a DIFFERENT call (the customer's
    history), not a moment in this one, so evidence_segment_id is None and
    the reason text names the earlier call instead.
  - "Call over 10 minutes" is a whole-call metric; we point at the final
    segment as the closest thing to "the moment this became true."
"""

NEGATIVE_MOODS = {"angry", "frustrated"}
MANAGER_KEYWORDS = ["manager", "supervisor", "escalate"]
LONG_CALL_SECONDS = 600


def _find_manager_request(segments: list[dict]) -> dict | None:
    for seg in segments:
        if seg["speaker"] != "customer":
            continue
        lower = seg["text"].lower()
        if any(kw in lower for kw in MANAGER_KEYWORDS):
            return {"segment_id": seg["id"], "quote": seg["text"]}
    return None


def compute_attention_score(
    *,
    resolution: str,
    final_mood: str,
    mood_events: list[dict],
    duration_seconds: float,
    is_repeat_contact: bool,
    repeat_contact_detail: str | None,
    segments: list[dict],
) -> tuple[int, list[dict]]:
    """
    Returns (score, reasons) where reasons is:
        [{ "reason": str, "points": int, "evidence_segment_id": str|None }, ...]
    """
    reasons: list[dict] = []

    if resolution == "unresolved":
        evidence = segments[-1]["id"] if segments else None
        reasons.append({"reason": "Unresolved issue", "points": 30, "evidence_segment_id": evidence})

    if final_mood in NEGATIVE_MOODS:
        customer_segments = [s for s in segments if s["speaker"] == "customer"]
        evidence = customer_segments[-1]["id"] if customer_segments else None
        reasons.append(
            {"reason": f"Customer ends call {final_mood}", "points": 20, "evidence_segment_id": evidence}
        )

    for event in mood_events:
        if event["mood_after"] in NEGATIVE_MOODS and event["mood_before"] not in NEGATIVE_MOODS:
            reasons.append(
                {
                    "reason": f"Mood shifted from {event['mood_before']} to {event['mood_after']}",
                    "points": 15,
                    "evidence_segment_id": event["segment_id"],
                }
            )
            break  # only counted once even if multiple negative shifts occur

    if is_repeat_contact:
        reasons.append(
            {
                "reason": f"Repeat contact - {repeat_contact_detail}",
                "points": 15,
                "evidence_segment_id": None,
            }
        )

    manager_hit = _find_manager_request(segments)
    if manager_hit:
        reasons.append(
            {
                "reason": f"Customer asked for a manager: \"{manager_hit['quote']}\"",
                "points": 10,
                "evidence_segment_id": manager_hit["segment_id"],
            }
        )

    if duration_seconds > LONG_CALL_SECONDS:
        evidence = segments[-1]["id"] if segments else None
        minutes = int(duration_seconds // 60)
        reasons.append(
            {
                "reason": f"Call ran {minutes}+ minutes (over the 10-minute threshold)",
                "points": 5,
                "evidence_segment_id": evidence,
            }
        )

    total = min(100, sum(r["points"] for r in reasons))
    return total, reasons
