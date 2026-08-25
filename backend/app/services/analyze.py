"""
AI analysis of one call transcript: intent, mood, resolution, summary.

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
        "model_used": str,                        # which model/provider actually produced this
    }

Every evidence_segment_id / mood_shift_segment_id is verified to actually exist
in `segments` before being returned — per the project brief, evidence that
doesn't hold up scores negative, so an id the model hallucinates is dropped
(set to None) rather than passed through.

Provider chain (each tier is a genuinely independent quota/failure domain):
    1. Groq GROQ_MODEL_CHAIN, in order — primary. Each model gets retried up
       to MAX_RETRIES with backoff for transient failures; a 429 (quota
       exhausted) skips straight to the next model with no wasted retries.
    2. Ollama (OLLAMA_MODEL), fully local/offline — the final, always-succeeds
       tier (mirrors step2_transcribe.py's faster-whisper role for
       transcription). No API key, no rate limit, no internet needed — just
       slow (CPU inference measured at ~140s/call on this machine), so it
       only gets used once Groq's whole chain is exhausted.

Uses JSON-mode / schema-constrained output on both (response_format=
{"type": "json_object"}; both are OpenAI-compatible APIs). Neither
guarantees schema conformance with 100% certainty, so the response is
always explicitly validated against CallAnalysisModel.

NOTE ON MODEL NAMES: verify against the live API before changing these —
model catalogs move fast and training data / SDK type hints lag behind.
Everything here was verified live while building this file, and every one
of these was wrong on first guess:
  - "gemini-1.5-flash" / "gemini-2.5-flash" (an earlier design) — both dead
    ("no longer available to new users"); Gemini was dropped entirely after
    also proving too flakey (~40% 503 "high demand" errors) and too rate
    limited (1500 req/day) to be a reliable primary for a 1441-call batch.
  - "llama-3.3-70b-versatile" (an earlier ask) — retired from this Groq
    account's catalog.
  - "deepseek-chat" — DeepSeek's models are now deepseek-v4-flash/-pro; moot
    anyway since that account had zero balance (402 Insufficient Balance).
  - meta-llama/llama-3.2-3b-instruct:free, google/gemma-2-9b-it:free,
    mistralai/mistral-7b-instruct:free, qwen/qwen-2-7b-instruct:free (an
    OpenRouter ask) — none exist on OpenRouter's current catalog. OpenRouter
    itself was then dropped from the chain entirely after also finding its
    free tier is capped at 50 requests/day account-wide (1000/day only
    after a $10+ credit purchase) — far too low to matter for a 1441-call
    batch, so it wasn't worth the added complexity.
Check client.models.list() (Groq SDK) before trusting a model name from memory.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Literal

import groq
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

# Windows consoles often default to cp1252, which can't encode the emoji in
# the provider-rotation prints below. Force UTF-8 defensively (see the same
# fix in step2_transcribe.py) so a log message can't crash the batch mid-run.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

GROQ_MODEL_CHAIN = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 3

# Closed mood vocabulary so attention_score.py's NEGATIVE_MOODS check is reliable
# regardless of phrasing the model might otherwise choose.
MOOD_VALUES = ("happy", "neutral", "confused", "frustrated", "angry")
MoodValue = Literal["happy", "neutral", "confused", "frustrated", "angry"]

_groq_client: groq.Groq | None = None
_ollama_client: OpenAI | None = None


def _get_groq_client() -> groq.Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise AnalysisError("GROQ_API_KEY is not set. Add it to backend/.env (see backend/.env.example).")
        _groq_client = groq.Groq(api_key=api_key)
    return _groq_client


def _get_ollama_client() -> OpenAI:
    global _ollama_client
    if _ollama_client is None:
        # Ollama's local server doesn't check the key, but the OpenAI client
        # requires a non-empty string.
        _ollama_client = OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL)
    return _ollama_client


class AnalysisError(RuntimeError):
    pass


class ModelUnavailableError(AnalysisError):
    """A model name is wrong or this key/account has no access to it (404/
    'does not exist'-type error) — as opposed to a transient failure or a
    quota limit. This is a configuration problem that will repeat identically
    for every remaining call, so batch_process.py stops the whole run on this
    rather than logging it as one more per-call failure and grinding through
    1400+ guaranteed-identical errors."""


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


def _try_ollama(formatted_text: str) -> tuple[CallAnalysisModel, str]:
    """Final, always-succeeds tier: fully local/offline via Ollama. Single
    attempt, no retry — if this fails too, something is fundamentally wrong
    (Ollama not running, model not pulled) rather than a transient issue."""
    client = _get_ollama_client()
    completion = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n\n{formatted_text}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1500,
    )
    raw = completion.choices[0].message.content
    if not raw:
        raise AnalysisError("Ollama returned an empty response")
    analysis = CallAnalysisModel.model_validate_json(_extract_json(raw))
    return analysis, f"{OLLAMA_MODEL} (ollama)"


def _try_groq_chain(formatted_text: str) -> tuple[CallAnalysisModel, str] | None:
    """Groq fallback: retries each model in GROQ_MODEL_CHAIN up to MAX_RETRIES
    with backoff; a 429 (quota exhausted) skips straight to the next model
    with no wasted retries. Returns None (not raises) if every model in the
    chain is exhausted, so the caller can report the combined failure."""
    client = _get_groq_client()
    last_error: Exception | None = None

    for model in GROQ_MODEL_CHAIN:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n\n{formatted_text}"},
        ]

        for attempt in range(1, MAX_RETRIES + 1):
            raw: str | None = None
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=1500,
                )
                raw = completion.choices[0].message.content
                if not raw:
                    raise AnalysisError("Groq returned an empty response")
                analysis = CallAnalysisModel.model_validate_json(_extract_json(raw))
                print(f"  ✅ Analysis succeeded using {model}")
                return analysis, model

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
                print(f"  ⚠️ {model} rate-limited (429) — switching to next model...")
                break  # do NOT retry an exhausted model, move straight to the next one
            except groq.NotFoundError as e:
                # Wrong model name, or this key/account has no access to it —
                # will fail identically on every remaining call. Stop here,
                # don't retry, don't switch models, don't fall through to Ollama.
                raise ModelUnavailableError(f"Groq model '{model}' not available: {e.message}") from e
            except groq.APIStatusError as e:
                if e.status_code == 404:
                    raise ModelUnavailableError(f"Groq model '{model}' not available: {e.message}") from e
                if e.status_code < 500:
                    raise AnalysisError(f"Groq API error ({e.status_code}): {e.message}") from e
                last_error = e
            except groq.APIConnectionError as e:
                last_error = e

            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(f"  [retry {attempt}/{MAX_RETRIES}] {model} failed ({last_error}); retrying in {wait}s...")
                time.sleep(wait)

        if not isinstance(last_error, groq.RateLimitError):
            print(f"  ⚠️ {model} failed after {MAX_RETRIES} attempts ({last_error}); trying next model...")

    return None


def analyze_call(formatted_text: str, segments: list[dict]) -> dict:
    """Tries the Groq model chain first, falls through to local Ollama
    (which should always succeed) once Groq is exhausted."""
    valid_ids = {seg["id"] for seg in segments}

    result = _try_groq_chain(formatted_text)

    if result is None:
        try:
            result = _try_ollama(formatted_text)
            print("  ✅ Ollama succeeded (offline)")
        except Exception as e:  # noqa: BLE001 - true last resort; nothing left to fall back to
            raise AnalysisError(
                f"Giving up on analysis after Groq + Ollama: {e}"
            ) from e

    analysis, model_used = result

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
        "model_used": model_used,
    }
