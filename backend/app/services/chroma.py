"""
ChromaDB semantic search over call summaries.

Each processed call's AI-generated summary (app/services/analyze.py) is stored
as a document and embedded with ChromaDB's bundled default embedding function
(no sentence-transformers model to manage ourselves) so managers can search
calls by meaning — "customer was really angry" — instead of exact keywords.

Storage: a local PersistentClient at data/chroma_db/, collection "vexora_calls".
id = call_id, document = summary, metadata = the fields needed to render a
result card without a second SQLite lookup (see _call_metadata).

Run directly to (re)sync every processed call from SQLite into ChromaDB:
    venv\\Scripts\\python.exe backend\\app\\services\\chroma.py
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))  # so `app.*` imports work when run as a plain script

import chromadb  # noqa: E402

from app.database.schema import Call, get_session  # noqa: E402

PROJECT_ROOT = BACKEND_ROOT.parent
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "vexora_calls"
BATCH_SIZE = 50
MIN_SIMILARITY = 0.3

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def get_chroma_collection() -> chromadb.Collection:
    """Connects to the local persistent ChromaDB store (creating data/chroma_db/
    if needed) and returns the "vexora_calls" collection, creating it on first use."""
    global _client, _collection
    if _collection is not None:
        return _collection

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # so similarity = 1 - distance lands in [0, 1]
    )
    return _collection


def _call_metadata(call: Call) -> dict:
    """Metadata stored alongside each embedding. Chroma rejects None values, so
    missing fields fall back to a safe default rather than being passed through."""
    return {
        "call_id": call.id,
        "customer_name": call.customer.name if call.customer else "",
        "agent_name": call.agent.name if call.agent else "",
        "intent": call.intent or "",
        "resolution": call.resolution or "unknown",
        "attention_score": call.attention_score if call.attention_score is not None else 0,
        "initial_mood": call.initial_mood or "unknown",
        "final_mood": call.final_mood or "unknown",
        "duration_seconds": call.duration_seconds,
    }


def sync_calls_to_chroma() -> None:
    """Reads every processed call with a summary from SQLite and embeds any that
    aren't already in ChromaDB (checked by call_id first, so re-runs are cheap),
    in batches of 50."""
    collection = get_chroma_collection()

    session = get_session()
    try:
        total_in_db = session.query(Call).count()
        if total_in_db == 0:
            print("No calls found in SQLite. Nothing to sync.")
            return

        calls = session.query(Call).filter(Call.summary.isnot(None)).all()
        skipped_no_summary = total_in_db - len(calls)
        if not calls:
            print(f"No calls have summaries yet ({total_in_db} calls total, all skipped). Nothing to sync.")
            return

        existing_ids = set(collection.get(include=[])["ids"])
        pending = [call for call in calls if call.id not in existing_ids]
        already_synced = len(calls) - len(pending)
        total = len(calls)

        if not pending:
            print(
                f"Synced {total}/{total} calls (already up to date; "
                f"{skipped_no_summary} skipped — no summary)."
            )
            return

        synced = already_synced
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            collection.add(
                ids=[call.id for call in batch],
                documents=[call.summary for call in batch],
                metadatas=[_call_metadata(call) for call in batch],
            )
            synced += len(batch)
            print(f"Synced {synced}/{total} calls")

        print(
            f"Done. Synced {len(pending)} new calls to ChromaDB "
            f"({already_synced} already present, {skipped_no_summary} skipped — no summary)."
        )
    finally:
        session.close()


def search_calls(query: str, n_results: int = 10) -> list[dict]:
    """Searches call summaries by meaning. Returns result dicts sorted by
    relevance, filtered to similarity_score > 0.3 (1.0 = perfect match)."""
    collection = get_chroma_collection()
    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    out = []
    for call_id, document, metadata, distance in zip(
        results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        similarity_score = 1 - distance  # cosine distance -> similarity
        if similarity_score <= MIN_SIMILARITY:
            continue
        out.append(
            {
                "call_id": call_id,
                "customer_name": metadata.get("customer_name", ""),
                "agent_name": metadata.get("agent_name", ""),
                "intent": metadata.get("intent", ""),
                "resolution": metadata.get("resolution", "unknown"),
                "attention_score": metadata.get("attention_score", 0),
                "similarity_score": round(similarity_score, 4),
                "summary": document,
            }
        )
    return out


def add_call_to_chroma(call_id: str, summary: str | None, metadata: dict) -> None:
    """Adds one newly processed call to ChromaDB, called from
    pipeline/process_one_call.py right after it's saved to SQLite so it's
    searchable immediately. No-ops if there's no summary or it's already present."""
    if not summary:
        return
    collection = get_chroma_collection()
    if collection.get(ids=[call_id])["ids"]:
        return
    collection.add(ids=[call_id], documents=[summary], metadatas=[metadata])


if __name__ == "__main__":
    sync_calls_to_chroma()
