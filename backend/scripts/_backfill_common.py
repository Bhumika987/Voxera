"""
Shared narrow-question AI helper for the one-off backfill scripts in this
directory (backfill_intent_category.py, backfill_resolution_evidence.py).

Deliberately isolated from app/services/analyze.py's GROQ_MODEL_CHAIN: these
backfills must never touch the openai/gpt-oss-120b tier, which is the model
the rest of the 1441-call dataset is held to and must stay fully available
for that quality bar rather than competing with narrow backfill requests.
Only openai/gpt-oss-20b (a separate Groq quota tier) is used, falling back to
local Ollama only if 20b itself is rate-limited or otherwise exhausted.
"""

import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

import groq  # noqa: E402

from app.services.analyze import OLLAMA_MODEL, _get_groq_client, _get_ollama_client  # noqa: E402

BACKFILL_GROQ_MODEL = "openai/gpt-oss-20b"
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 3


def ask(system_prompt: str, user_prompt: str, max_tokens: int, ollama_only: bool = False) -> tuple[str, str]:
    """Returns (raw_text, model_used_label). Tries Groq 20b (retrying transient
    failures, breaking straight to Ollama on a 429), then falls back to local
    Ollama as the always-succeeds last resort. Pass ollama_only=True to skip
    Groq entirely (e.g. once its daily quota is known to be exhausted, so
    calls aren't wasted on requests that will just 429).

    reasoning_effort="low": gpt-oss-20b is a reasoning model that spends
    completion tokens on a hidden "reasoning" field before the actual answer.
    Without this, a small max_tokens (fine for these one-word/one-id answers)
    gets consumed entirely by reasoning, leaving the real content empty."""
    if ollama_only:
        return _ask_ollama(system_prompt, user_prompt, max_tokens)

    client = _get_groq_client()
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            completion = client.chat.completions.create(
                model=BACKFILL_GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                reasoning_effort="low",
            )
            raw = completion.choices[0].message.content
            if raw:
                return raw.strip(), BACKFILL_GROQ_MODEL
        except groq.RateLimitError as e:
            last_error = e
            break  # exhausted — go straight to Ollama, don't retry
        except Exception as e:  # noqa: BLE001
            last_error = e

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

    print(f"  ⚠️ Groq {BACKFILL_GROQ_MODEL} failed ({last_error}); falling back to local Ollama...")
    return _ask_ollama(system_prompt, user_prompt, max_tokens)


def _ask_ollama(system_prompt: str, user_prompt: str, max_tokens: int) -> tuple[str, str]:
    ollama = _get_ollama_client()
    completion = ollama.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    raw = completion.choices[0].message.content
    return raw.strip(), f"{OLLAMA_MODEL} (ollama)"
