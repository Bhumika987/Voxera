"""
One-time migration: add the two new nullable columns backing Fix 2 (resolution
evidence) and Fix 3 (intent category) to the existing live calls table.

init_db()/Base.metadata.create_all() only creates missing tables, never adds
columns to an existing one, so this follows the same manual ALTER TABLE
pattern already used earlier this session for model_used/transcription_provider.

Idempotent: checks PRAGMA table_info(calls) first and skips any column that's
already present, so it's safe to re-run.

Run directly:
    venv\\Scripts\\python.exe backend\\scripts\\migrate_add_columns.py
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.database.schema import engine  # noqa: E402

NEW_COLUMNS = {
    "resolution_evidence_segment_id": "VARCHAR(32)",
    "intent_category": "VARCHAR(32)",
}


def main() -> None:
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(calls)"))}
        for col, coltype in NEW_COLUMNS.items():
            if col in existing:
                print(f"  skip: {col} already exists")
                continue
            conn.execute(text(f"ALTER TABLE calls ADD COLUMN {col} {coltype}"))
            conn.commit()
            print(f"  added: {col} {coltype}")


if __name__ == "__main__":
    main()
