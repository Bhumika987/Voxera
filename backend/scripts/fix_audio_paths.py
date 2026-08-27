"""
One-time backfill: rewrite calls.audio_path from an absolute, machine-specific
path to a repo-relative "data/audio/{id}.mp3" path.

No AI involved — every row's audio filename stem is already equal to Call.id
(the schema's own invariant), so the correct value is derived purely from the
primary key rather than string-replacing the old absolute prefix.

Idempotent by construction: the computed value depends only on `id`, so
re-running this at any time (interrupted or not) is always safe.

Run directly:
    venv\\Scripts\\python.exe backend\\scripts\\fix_audio_paths.py --dry-run
    venv\\Scripts\\python.exe backend\\scripts\\fix_audio_paths.py --limit 5
    venv\\Scripts\\python.exe backend\\scripts\\fix_audio_paths.py
"""

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.database.schema import engine  # noqa: E402


def _rows_to_fix(conn, limit: int | None) -> list[tuple[str, str, str]]:
    """Returns (id, old_audio_path, new_audio_path) for every row whose
    audio_path isn't already the correct relative form."""
    query = "SELECT id, audio_path FROM calls ORDER BY id"
    if limit is not None:
        query += f" LIMIT {limit}"
    rows = conn.execute(text(query)).fetchall()

    result = []
    for call_id, old_path in rows:
        new_path = f"data/audio/{call_id}.mp3"
        if old_path != new_path:
            result.append((call_id, old_path, new_path))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite calls.audio_path to a repo-relative path.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change, write nothing.")
    parser.add_argument("--limit", type=int, default=None, help="Only consider the first N calls (by id).")
    args = parser.parse_args()

    with engine.connect() as conn:
        to_fix = _rows_to_fix(conn, args.limit)

        if not to_fix:
            print("Nothing to fix — every considered row already has a relative audio_path.")
            return

        for call_id, old_path, new_path in to_fix:
            print(f"  {call_id}: {old_path!r} -> {new_path!r}")

        if args.dry_run:
            print(f"\n[dry run] {len(to_fix)} row(s) would be updated. No changes written.")
            return

        for call_id, _old_path, new_path in to_fix:
            conn.execute(
                text("UPDATE calls SET audio_path = :new_path WHERE id = :id"),
                {"new_path": new_path, "id": call_id},
            )
        conn.commit()
        print(f"\nUpdated {len(to_fix)} row(s).")


if __name__ == "__main__":
    main()
