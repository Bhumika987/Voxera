"""
AI analysis of one call transcript: intent, mood, resolution, summary — via Groq.

CONTRACT (relied on by pipeline/process_one_call.py; keep stable):

Input:
    formatted_text: str
        The whole call as plain text, e.g.:
            [seg_1][00:00-00:04] AGENT: Thank you for calling...
            [seg_2][00:05-00:13] CUSTOMER: My card was charged twice...
    segments: list[dict]
        [{ "id": "seg_1", "speaker": "agent"|"customer", "start": float, "end": float, "text": str }, ...]

Output: a dict with exactly these keys:
    {
        "intent": str,
        "intent_evidence_segment_id": str|None,
        "resolution": "resolved" | "unresolved" | "unknown",
        "summary": str,                          # <= 40 words
        "initial_mood": str, "final_mood": str,   # one of MOOD_VALUES
        "mood_events": [{ "timestamp": float, "mood_before": str, "mood_after": str, "segment_id": str }, ...],
        "mood_shift_time": float|None,
        "mood_shift_segment_id": float|None,
    }

Every evidence_segment_id / mood_shift_segment_id is verified to actually exist
in `segments` before being returned — per the project brief, evidence that
doesn't hold up scores negative, so an id the model hallucinates is dropped
(set to None) rather than passed through.

Uses Groq's OpenAI-compatible chat completions API with JSON mode
(response_format={"type": "json_object"}). Unlike Anthropic's constrained
decoding, JSON mode only guarantees *valid JSON*, not schema conformance —
so the response is explicitly validated against CallAnalysisModel and retried
(with the validation error fed back to the model) if it doesn't match.
"""

import json
import os
import time
from pathlib import Path
from typing import Literal

import groq
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

# Groq model to use — swap here if this one is retired. Verify against your
# account's actual available models with: client.models.list()
# (the SDK's type hints can lag behind — llama-3.3-70b-versatile, for example,
# is listed there but was already retired from this account's catalog).
MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 3

# Closed mood vocabulary so attention_score.py's NEGATIVE_MOODS check is reliable
# regardless of phrasing the model might otherwise choose.
MOOD_VALUES = ("happy", "neutral", "confused", "frustrated", "angry")
MoodValue = Literal["happy", "neutral", "confused", "frustrated", "angry"]

_client: groq.Groq | None = None


def _get_client() -> groq.Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise AnalysisError("GROQ_API_KEY is not set. Add it to backend/.env (see backend/.env.example).")
        _client = groq.Groq(api_key=api_key)
    return _client


class AnalysisError(RuntimeError):
    pass


class MoodEventModel(BaseModel):
    timestamp: float
    mood_before: MoodValue
    mood_after: MoodValue
    segment_id: str


class CallAnalysisModel(BaseModel):
    intent: str
    intent_evidence_segment_id: str | None = None
    resolution: Literal["resolved", "unresolved", "unknown"]
    summary: str
    initial_mood: MoodValue
    final_mood: MoodValue
    mood_events: list[MoodEventModel] = []
    mood_shift_time: float | None = None
    mood_shift_segment_id: str | None = None


SYSTEM_PROMPT = f"""You are analyzing a bank customer support call transcript for a manager dashboard.

Every claim you make must be grounded in the transcript. For every evidence_segment_id
you return, that segment id must actually appear in the transcript AND its text must
actually support the claim you're making — evidence that doesn't hold up is worse than
no evidence, so if you're not sure, use null rather than guess.

Rules:
- intent: what the customer actually wanted, in a short paraphrase (not just quoting their first line — read the whole call to find their real goal).
- intent_evidence_segment_id: the segment id where the customer states or reveals that intent.
- resolution: "resolved" only if the transcript shows the issue was actually addressed by the end of the call; "unresolved" if it clearly wasn't; "unknown" if the transcript doesn't make it clear either way.
- summary: <= 40 words, plain language, what happened and the outcome.
- initial_mood / final_mood: the customer's mood at the start vs end of the call. Must be exactly one of: {", ".join(MOOD_VALUES)}.
- mood_events: every time the customer's mood meaningfully changed during the call, in order, each with the exact segment id and timestamp where the shift becomes evident. Empty list if mood never shifted.
- mood_shift_time / mood_shift_segment_id: the single MOST significant mood shift (usually the biggest drop), matching one of the mood_events. Both null if mood never shifted.

Respond with ONLY a single JSON object (no markdown, no code fences, no commentary) matching exactly this shape:
{{
  "intent": "<string>",
  "intent_evidence_segment_id": "<segment id or null>",
  "resolution": "resolved" | "unresolved" | "unknown",
  "summary": "<string, <=40 words>",
  "initial_mood": "<one of: {", ".join(MOOD_VALUES)}>",
  "final_mood": "<one of: {", ".join(MOOD_VALUES)}>",
  "mood_events": [{{"timestamp": <number>, "mood_before": "<mood>", "mood_after": "<mood>", "segment_id": "<segment id>"}}],
  "mood_shift_time": <number or null>,
  "mood_shift_segment_id": "<segment id or null>"
}}
"""


def _extract_json(raw: str) -> str:
    """Strip markdown code fences if the model wraps its JSON despite instructions."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _validate_segment_id(segment_id: str | None, valid_ids: set[str]) -> str | None:
    return segment_id if segment_id in valid_ids else None


def analyze_call(formatted_text: str, segments: list[dict]) -> dict:
    """Calls Groq to analyze one call transcript. Retries transient API failures
    and malformed/non-conforming JSON (feeding the validation error back to the model)."""
    valid_ids = {seg["id"] for seg in segments}
    client = _get_client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Transcript:\n\n{formatted_text}"},
    ]

    last_error: Exception | None = None
    analysis: CallAnalysisModel | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        raw: str | None = None
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1500,
            )
            raw = completion.choices[0].message.content
            if not raw:
                raise AnalysisError("Groq returned an empty response")
            analysis = CallAnalysisModel.model_validate_json(_extract_json(raw))
            break

        except (json.JSONDecodeError, ValidationError, AnalysisError) as e:
            last_error = e
            # feed the error back so the retry can self-correct
            messages.append({"role": "assistant", "content": raw or "(empty response)"})
            messages.append(
                {
                    "role": "user",
                    "content": f"That wasn't valid JSON matching the required schema ({e}). "
                    "Respond again with ONLY the corrected JSON object, no other text.",
                }
            )
        except groq.RateLimitError as e:
            last_error = e
        except groq.APIStatusError as e:
            if e.status_code < 500:
                raise AnalysisError(f"Groq API error ({e.status_code}): {e.message}") from e
            last_error = e
        except groq.APIConnectionError as e:
            last_error = e

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"  [retry {attempt}/{MAX_RETRIES}] Groq analysis failed ({last_error}); retrying in {wait}s...")
            time.sleep(wait)

    if analysis is None:
        raise AnalysisError(f"Giving up on Groq analysis after {MAX_RETRIES} attempts: {last_error}") from last_error

    mood_events = [
        {
            "timestamp": e.timestamp,
            "mood_before": e.mood_before,
            "mood_after": e.mood_after,
            "segment_id": e.segment_id,
        }
        for e in analysis.mood_events
        if e.segment_id in valid_ids
    ]

    mood_shift_segment_id = _validate_segment_id(analysis.mood_shift_segment_id, valid_ids)
    mood_shift_time = analysis.mood_shift_time if mood_shift_segment_id else None

    return {
        "intent": analysis.intent,
        "intent_evidence_segment_id": _validate_segment_id(analysis.intent_evidence_segment_id, valid_ids),
        "resolution": analysis.resolution,
        "summary": " ".join(analysis.summary.split()[:40]),
        "initial_mood": analysis.initial_mood,
        "final_mood": analysis.final_mood,
        "mood_events": mood_events,
        "mood_shift_time": mood_shift_time,
        "mood_shift_segment_id": mood_shift_segment_id,
    }
