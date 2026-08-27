"""
One-time backfill: classify each existing call's free-text `intent` into the
closed INTENT_CATEGORIES vocabulary (see app/services/analyze.py), so
/api/trends can group calls without free-text phrasing fragmenting
semantically-identical intents apart.

Narrow question, not full re-analysis: sends only the short `intent` string
(a few words) to the model, not the transcript. Uses backend/scripts/
_backfill_common.py's Groq 20b -> Ollama chain (never 120b — see that file's
docstring for why).

Resumable by construction: the driving query only selects rows where
intent_category is still NULL, so re-running after an interruption picks up
exactly where it left off.

Run directly:
    venv\\Scripts\\python.exe backend\\scripts\\backfill_intent_category.py --limit 5
    venv\\Scripts\\python.exe backend\\scripts\\backfill_intent_category.py
"""

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from _backfill_common import ask  # noqa: E402
from app.database.schema import engine  # noqa: E402
from app.services.analyze import INTENT_CATEGORIES  # noqa: E402

SYSTEM_PROMPT = (
    "Classify this bank customer support call's intent into exactly one category.\n"
    f"Categories: {', '.join(INTENT_CATEGORIES)}.\n"
    "Respond with ONLY the category name, nothing else."
)


def _classify(intent_text: str) -> tuple[str, str]:
    """Returns (category, model_used). Falls back to OTHER if the model's
    answer doesn't match the closed vocabulary."""
    raw, model_used = ask(SYSTEM_PROMPT, f'Intent: "{intent_text}"', max_tokens=64)
    category = raw.strip().upper().strip('."\' ')
    if category not in INTENT_CATEGORIES:
        category = "OTHER"
    return category, model_used


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill calls.intent_category from calls.intent.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N rows (by id).")
    args = parser.parse_args()

    with engine.connect() as conn:
        query = "SELECT id, intent FROM calls WHERE intent_category IS NULL AND intent IS NOT NULL ORDER BY id"
        if args.limit is not None:
            query += f" LIMIT {args.limit}"
        rows = conn.execute(text(query)).fetchall()

        if not rows:
            print("Nothing to do — every considered row already has an intent_category.")
            return

        print(f"Classifying {len(rows)} call(s)...")
        for i, (call_id, intent_text) in enumerate(rows, start=1):
            category, model_used = _classify(intent_text)
            conn.execute(
                text("UPDATE calls SET intent_category = :category WHERE id = :id"),
                {"category": category, "id": call_id},
            )
            conn.commit()
            print(f"  [{i}/{len(rows)}] {call_id}: {intent_text!r} -> {category} ({model_used})")

        print(f"\nDone. Classified {len(rows)} row(s).")


if __name__ == "__main__":
    main()
