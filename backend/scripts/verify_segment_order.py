"""
Read-only verification: confirms that applying the new explicit
(start, agent-before-customer) tiebreak to each call's existing
transcript_segments produces the exact same order they're already
stored in. Writes nothing — segment_ids are referenced by evidence
fields elsewhere (Call.*_segment_id, AttentionReason, MoodEvent), so
re-numbering them would break those references for a fix that (per
the 9 known tie cases) doesn't actually change anything.

Run directly:
    venv\\Scripts\\python.exe backend\\scripts\\verify_segment_order.py
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.database.schema import engine  # noqa: E402


def main() -> None:
    with engine.connect() as conn:
        call_ids = [r[0] for r in conn.execute(text("SELECT id FROM calls"))]

        mismatches = []
        ties_checked = 0

        for call_id in call_ids:
            rows = conn.execute(
                text(
                    "SELECT segment_id, speaker, start_time FROM transcript_segments "
                    "WHERE call_id = :call_id ORDER BY id"
                ),
                {"call_id": call_id},
            ).fetchall()

            stored_order = [r[0] for r in rows]
            resorted = sorted(rows, key=lambda r: (r[2], 0 if r[1] == "agent" else 1))
            new_order = [r[0] for r in resorted]

            # count exact start_time ties in this call for reporting
            starts = [r[2] for r in rows]
            if len(starts) != len(set(starts)):
                ties_checked += 1

            if stored_order != new_order:
                mismatches.append((call_id, stored_order, new_order))

        print(f"Calls checked: {len(call_ids)}")
        print(f"Calls with an exact start_time tie: {ties_checked}")
        print(f"Calls where the new tiebreak would change order: {len(mismatches)}")

        for call_id, old, new in mismatches:
            print(f"  MISMATCH {call_id}: stored={old} vs new={new}")

        if not mismatches:
            print("\nAll existing transcript_segments already match the new explicit tiebreak order.")
            print("No backfill needed — this fix only affects calls processed from now on.")


if __name__ == "__main__":
    main()
