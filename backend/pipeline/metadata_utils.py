"""
Parse a call's metadata JSON into the flat shape the rest of the pipeline expects.

The real files are NOT flat ({"customer_name": ..., "agent_name": ..., "timestamp": ...}
as originally assumed) — verified against the actual dataset, the shape is:

    {
      "sid": "004860b1ab2e4c88",
      "start_time_ms": 1590860609249,
      "end_time_ms": 1590860654497,
      "caller": { "metadata": { "first and last name": "Mary Smith" }, ... },
      "agent":  { "metadata": { "agent_name": "Robert" }, ... },
      "session": "Little Harper Valley 2"
    }

start_time_ms / end_time_ms are Unix epoch milliseconds.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class MetadataError(RuntimeError):
    """Raised when a metadata file is missing an expected field."""


def parse_metadata(metadata_path: Path) -> dict:
    """
    Returns:
        {
            "call_id": str,
            "customer_name": str,
            "agent_name": str,
            "started_at": datetime,       # UTC
            "duration_seconds": float,    # from end_time_ms - start_time_ms
        }
    """
    metadata_path = Path(metadata_path)
    if not metadata_path.exists():
        raise MetadataError(f"Metadata file not found: {metadata_path}")

    data = json.loads(metadata_path.read_text(encoding="utf-8"))

    try:
        call_id = data["sid"]
        customer_name = data["caller"]["metadata"]["first and last name"].strip()
        agent_name = data["agent"]["metadata"]["agent_name"].strip()
        start_ms = data["start_time_ms"]
        end_ms = data["end_time_ms"]
    except KeyError as e:
        raise MetadataError(f"{metadata_path.name}: missing expected field {e}") from e

    return {
        "call_id": call_id,
        "customer_name": customer_name,
        "agent_name": agent_name,
        "started_at": datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc),
        "duration_seconds": max(0.0, (end_ms - start_ms) / 1000.0),
    }
