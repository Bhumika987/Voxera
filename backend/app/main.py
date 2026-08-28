from typing import Generator

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from fastapi import HTTPException
from app.database.schema import (
    get_session,
    Call,
    Customer,
    Agent,
    TranscriptSegment,
    AttentionReason,
    MoodEvent,
)
from pathlib import Path
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy import case

# chroma is imported lazily inside the endpoint to avoid import-time failures


app = FastAPI(title="Vexora API")

# Allow common local dev origins (frontend running on 3000 or 5173).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLAlchemy session and ensures
    it is closed after the request completes.
    """
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Return a simple health object including a dynamic count of calls
    stored in the database (from the `calls` table).
    """
    total_calls = db.query(Call).count()
    return {"status": "ok", "total_calls": total_calls}


@app.get("/api/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db)) -> dict:
    """Return aggregated dashboard numbers computed from processed calls.

    - Only counts calls where `processed` is True.
    - `resolved` / `unresolved` / `unknown` are counted from Call.resolution values
      (a small number of calls have an "unknown" resolution when the transcript
      didn't make the outcome clear — these still count toward `total_calls` and
      the `resolution_rate` denominator, they just aren't resolved or unresolved).
    - `resolution_rate` is percentage (resolved / total_calls) * 100 rounded to 2 decimals.
    - `mood_distribution` tallies observed `final_mood` values.
    - `needs_attention`: no project-wide threshold exists for "needs attention" in
      the codebase, so this implementation returns 0 and leaves the KPI undefined
      until a threshold is agreed. See the developer response for options.
    """
    total_calls = db.query(Call).filter(Call.processed.is_(True)).count()

    resolved = db.query(func.count()).filter(Call.processed.is_(True), Call.resolution == "resolved").scalar() or 0
    unresolved = db.query(func.count()).filter(Call.processed.is_(True), Call.resolution == "unresolved").scalar() or 0
    unknown = db.query(func.count()).filter(Call.processed.is_(True), Call.resolution == "unknown").scalar() or 0

    # mood distribution: group by final_mood
    mood_rows = db.query(Call.final_mood, func.count()).filter(Call.processed.is_(True)).group_by(Call.final_mood).all()
    mood_distribution: dict = {}
    for mood, cnt in mood_rows:
        mood_key = mood if mood is not None else "unknown"
        mood_distribution[mood_key] = cnt

    # Ensure common moods appear even if zero to keep response stable for frontend
    for expected in ("neutral", "frustrated", "angry", "happy", "confused"):
        mood_distribution.setdefault(expected, 0)

    if total_calls == 0:
        resolution_rate = 0.0
    else:
        resolution_rate = round((resolved / total_calls) * 100.0, 2)

    # needs_attention: calls with attention_score >= 30 OR explicit manager/escalation reason
    # First: calls with attention_score >= 30
    high_score_ids = {row[0] for row in db.query(Call.id).filter(Call.processed.is_(True), Call.attention_score >= 30).all()}

    # Second: calls with an attention reason that is an explicit manager/escalation request
    # Match common keywords used by the scoring rules (manager, supervisor, escalate)
    manager_kw = ("manager", "supervisor", "escalat")
    # Use a case-insensitive LIKE search on AttentionReason.reason
    manager_ids = set()
    for kw in manager_kw:
        rows = db.query(AttentionReason.call_id).filter(AttentionReason.call_id == Call.id)
        # Note: the above generic filter can't reference Call in this context; use a direct query on AttentionReason
        rows = db.query(AttentionReason.call_id).filter(AttentionReason.reason.ilike(f"%{kw}%")).all()
        manager_ids.update({r[0] for r in rows})

    # Restrict to processed calls only
    if manager_ids:
        processed_manager_ids = {cid for cid in manager_ids if db.query(Call).filter(Call.id == cid, Call.processed.is_(True)).count()}
    else:
        processed_manager_ids = set()

    needs_ids = high_score_ids.union(processed_manager_ids)
    needs_attention = len(needs_ids)

    return {
        "total_calls": total_calls,
        "resolved": resolved,
        "unresolved": unresolved,
        "unknown": unknown,
        "resolution_rate": resolution_rate,
        "needs_attention": needs_attention,
        "mood_distribution": mood_distribution,
    }



@app.get("/api/calls/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_db)) -> dict:
    """Return a single processed call with related records for frontend rendering.

    Returns 404 if the call is not found or not processed.
    """
    call = db.get(Call, call_id)
    if call is None or not call.processed:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found or not processed")

    customer = {"id": call.customer.id, "name": call.customer.name} if call.customer else None
    agent = {"id": call.agent.id, "name": call.agent.name} if call.agent else None

    # basic call fields
    out = {
        "call_id": call.id,
        "customer": customer,
        "agent": agent,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "duration_seconds": call.duration_seconds,
        "intent": call.intent,
        "intent_evidence_segment_id": call.intent_evidence_segment_id,
        "resolution": call.resolution,
        "summary": call.summary,
        "attention_score": call.attention_score,
        "initial_mood": call.initial_mood,
        "final_mood": call.final_mood,
        "mood_shift_time": call.mood_shift_time,
        "mood_shift_segment_id": call.mood_shift_segment_id,
    }

    # transcript segments ordered chronologically
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.call_id == call.id)
        .order_by(TranscriptSegment.start_time)
        .all()
    )
    out_transcript = []
    seg_map = {}
    for s in segments:
        item = {
            "segment_id": s.segment_id,
            "speaker": s.speaker,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "text": s.text,
        }
        out_transcript.append(item)
        seg_map[s.segment_id] = item
    out["transcript"] = out_transcript

    # attention reasons with evidence text/timestamp where available
    reasons = db.query(AttentionReason).filter(AttentionReason.call_id == call.id).all()
    out_reasons = []
    for r in reasons:
        evidence = None
        if r.evidence_segment_id:
            evidence = seg_map.get(r.evidence_segment_id)
        out_reasons.append(
            {
                "reason": r.reason,
                "points": r.points,
                "evidence_segment_id": r.evidence_segment_id,
                "evidence_text": evidence["text"] if evidence else None,
                "evidence_start_time": evidence["start_time"] if evidence else None,
            }
        )
    out["attention_reasons"] = out_reasons

    # mood events timeline
    mood_events = db.query(MoodEvent).filter(MoodEvent.call_id == call.id).order_by(MoodEvent.timestamp).all()
    out_mood_events = []
    for me in mood_events:
        ev = seg_map.get(me.segment_id)
        out_mood_events.append(
            {
                "timestamp": me.timestamp,
                "mood_before": me.mood_before,
                "mood_after": me.mood_after,
                "segment_id": me.segment_id,
                "evidence_text": ev["text"] if ev else None,
                "evidence_start_time": ev["start_time"] if ev else None,
            }
        )
    out["mood_events"] = out_mood_events

    # AI evidence: intent and mood shift segment details (if present)
    ai_evidence = {}
    if call.intent_evidence_segment_id:
        seg = seg_map.get(call.intent_evidence_segment_id)
        ai_evidence["intent_evidence"] = {
            "segment_id": call.intent_evidence_segment_id,
            "text": seg["text"] if seg else None,
            "start_time": seg["start_time"] if seg else None,
        }
    if call.mood_shift_segment_id:
        seg = seg_map.get(call.mood_shift_segment_id)
        ai_evidence["mood_shift_evidence"] = {
            "segment_id": call.mood_shift_segment_id,
            "text": seg["text"] if seg else None,
            "start_time": seg["start_time"] if seg else None,
            "mood_shift_time": call.mood_shift_time,
        }
    out["ai_evidence"] = ai_evidence

    # Note: resolution evidence is not stored in the schema explicitly if present.
    out["resolution_evidence_available"] = False

    return out



@app.get("/api/attention")
def list_attention(db: Session = Depends(get_db)) -> dict:
    """Return up to 20 processed calls that qualify for manager attention,
    ordered by attention_score descending.

    Qualification: processed AND (attention_score >= 30 OR attention reason contains manager/supervisor/escalat)
    """
    manager_kw = ("manager", "supervisor", "escalat")
    or_clauses = [AttentionReason.reason.ilike(f"%{kw}%") for kw in manager_kw]

    # subquery of call_ids with manager-like reasons
    mgr_subq = db.query(AttentionReason.call_id).filter(or_(*or_clauses)).subquery()

    # main query: processed calls that either have high score or are in mgr_subq
    q = (
        db.query(Call)
        .filter(Call.processed.is_(True))
        .filter(or_(Call.attention_score >= 30, Call.id.in_(mgr_subq)))
        .order_by(Call.attention_score.desc())
        .limit(20)
    )

    calls = q.all()

    out_calls = []
    for c in calls:
        # determine top reason for this call (highest points, deterministic tie by id)
        top = (
            db.query(AttentionReason)
            .filter(AttentionReason.call_id == c.id)
            .order_by(AttentionReason.points.desc(), AttentionReason.id.asc())
            .first()
        )
        top_reason = top.reason if top else None

        out_calls.append(
            {
                "call_id": c.id,
                "customer_name": c.customer.name if c.customer else None,
                "agent_name": c.agent.name if c.agent else None,
                "attention_score": c.attention_score,
                "intent": c.intent,
                "resolution": c.resolution,
                "final_mood": c.final_mood,
                "duration_seconds": c.duration_seconds,
                "top_reason": top_reason,
            }
        )

    return {"count": len(out_calls), "calls": out_calls}


@app.get("/api/customers")
def list_customers(db: Session = Depends(get_db)) -> dict:
    """Return customers that have processed calls with aggregated stats.

    - total_calls: count of processed calls for the customer
    - unresolved_calls: count where resolution == 'unresolved'
    - last_call_at: latest started_at among processed calls
    - avg_attention_score: average of attention_score (NULLs ignored), rounded to 2 decimals
    """
    # Build aggregation over processed calls
    unresolved_case = case((Call.resolution == "unresolved", 1), else_=0)

    rows = (
        db.query(
            Customer.id.label("customer_id"),
            Customer.name.label("name"),
            func.count(Call.id).label("total_calls"),
            func.sum(unresolved_case).label("unresolved_calls"),
            func.max(Call.started_at).label("last_call_at"),
            func.avg(Call.attention_score).label("avg_attention_score"),
        )
        .join(Call, Call.customer_id == Customer.id)
        .filter(Call.processed.is_(True))
        .group_by(Customer.id)
        .order_by(func.max(Call.started_at).desc(), Customer.id.asc())
        .all()
    )

    customers = []
    for r in rows:
        avg = float(r.avg_attention_score) if r.avg_attention_score is not None else 0.0
        customers.append(
            {
                "customer_id": r.customer_id,
                "name": r.name,
                "total_calls": int(r.total_calls),
                "unresolved_calls": int(r.unresolved_calls or 0),
                "last_call_at": r.last_call_at.isoformat() if r.last_call_at is not None else None,
                "avg_attention_score": round(avg, 2),
            }
        )

    return {"count": len(customers), "customers": customers}



@app.get("/api/customers/{customer_id}/calls")
def customer_calls(customer_id: int, db: Session = Depends(get_db)) -> dict:
    """Return processed call history for one customer, newest first.

    Returns 404 if the customer does not exist.
    """
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    calls = (
        db.query(Call)
        .filter(Call.customer_id == customer.id, Call.processed.is_(True))
        .order_by(Call.started_at.desc())
        .all()
    )

    out_calls = []
    for c in calls:
        out_calls.append(
            {
                "call_id": c.id,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "duration_seconds": c.duration_seconds,
                "intent": c.intent,
                "resolution": c.resolution,
                "summary": c.summary,
                "attention_score": c.attention_score,
                "initial_mood": c.initial_mood,
                "final_mood": c.final_mood,
            }
        )

    return {"customer_id": customer.id, "customer_name": customer.name, "total_calls": len(out_calls), "calls": out_calls}


@app.get("/api/agents")
def list_agents(db: Session = Depends(get_db)) -> dict:
    """Return agents that have processed calls with aggregated performance stats.

    - Only counts processed calls.
    - Uses the same manager-attention rule as other endpoints (attention_score >= 30
      OR AttentionReason.reason contains manager/supervisor/escalat).
    """
    # Prepare manager keyword subquery for attention reasons
    manager_kw = ("manager", "supervisor", "escalat")
    or_clauses = [AttentionReason.reason.ilike(f"%{kw}%") for kw in manager_kw]
    mgr_subq = db.query(AttentionReason.call_id).filter(or_(*or_clauses)).subquery()

    # Aggregate per-agent over processed calls
    unresolved_case = case((Call.resolution == "unresolved", 1), else_=0)

    rows = (
        db.query(
            Agent.id.label("agent_id"),
            Agent.name.label("name"),
            func.count(Call.id).label("total_calls"),
            func.sum(case((Call.resolution == "resolved", 1), else_=0)).label("resolved"),
            func.sum(unresolved_case).label("unresolved"),
            func.avg(Call.duration_seconds).label("avg_duration"),
        )
        .join(Call, Call.agent_id == Agent.id)
        .filter(Call.processed.is_(True))
        .group_by(Agent.id)
        .order_by(func.count(Call.id).desc(), Agent.id.asc())
        .all()
    )

    agents = []
    for r in rows:
        agent_id = int(r.agent_id)
        total_calls = int(r.total_calls or 0)
        resolved = int(r.resolved or 0)
        unresolved = int(r.unresolved or 0)

        if total_calls == 0:
            resolution_rate = 0.0
        else:
            resolution_rate = round((resolved / total_calls) * 100.0, 2)

        avg_duration = round(float(r.avg_duration), 2) if r.avg_duration is not None else 0.0

        # attention_calls: processed calls for this agent that either have high score
        # or match the manager-like attention reason. Do not double-count.
        attention_count = (
            db.query(func.count())
            .filter(
                Call.agent_id == agent_id,
                Call.processed.is_(True),
                or_(Call.attention_score >= 30, Call.id.in_(mgr_subq)),
            )
            .scalar()
            or 0
        )

        agents.append(
            {
                "agent_id": agent_id,
                "name": r.name,
                "total_calls": total_calls,
                "resolved": resolved,
                "unresolved": unresolved,
                "resolution_rate": resolution_rate,
                "avg_duration": avg_duration,
                "attention_calls": int(attention_count),
            }
        )

    return {"count": len(agents), "agents": agents}


@app.get("/api/trends")
def list_trends(db: Session = Depends(get_db)) -> dict:
    """Return top intents (by processed call count) with unresolved counts and avg attention.

    - Uses only processed calls.
    - Groups by `Call.intent` (keeps distinct text values).
    - If any NULL/blank intents exist in the DB they will be reported as 'Unknown'.
    """
    # Check for NULL/blank intents existence; if present we'll map them to 'Unknown'
    null_count = db.query(func.count()).filter(Call.processed.is_(True), or_(Call.intent.is_(None), Call.intent == "")).scalar() or 0

    # Build grouping key: map NULL/empty to 'Unknown' when present, otherwise use raw intent
    if null_count:
        intent_key = case((Call.intent.is_(None), "Unknown"), (Call.intent == "", "Unknown"), else_=Call.intent).label("intent")
    else:
        intent_key = Call.intent.label("intent")

    unresolved_case = case((Call.resolution == "unresolved", 1), else_=0)

    rows = (
        db.query(
            intent_key,
            func.count(Call.id).label("count"),
            func.sum(unresolved_case).label("unresolved_count"),
            func.avg(Call.attention_score).label("avg_attention_score"),
        )
        .filter(Call.processed.is_(True))
        .group_by(intent_key)
        .order_by(func.count(Call.id).desc(), intent_key.asc())
        .limit(10)
        .all()
    )

    trends = []
    for r in rows:
        intent_val = r.intent
        cnt = int(r.count or 0)
        unresolved = int(r.unresolved_count or 0)
        avg_att = round(float(r.avg_attention_score), 2) if r.avg_attention_score is not None else 0.0
        trends.append({
            "intent": intent_val,
            "count": cnt,
            "unresolved_count": unresolved,
            "avg_attention_score": avg_att,
        })

    return {"count": len(trends), "trends": trends}


@app.get("/api/search")
def search(q: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Thin wrapper around the existing ChromaDB semantic search.

    - `q` is required and trimmed.
    - Uses `app.services.chroma.search_calls` and returns its results directly
      inside a small envelope: `{query, count, results}`.
    """
    if q is None:
        raise HTTPException(status_code=400, detail="Missing required query parameter 'q'")
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query 'q' must not be empty or whitespace")

    try:
        # lazy import to avoid crashing if chromadb isn't installed or the collection isn't available
        from app.services import chroma as chroma_service
        results = chroma_service.search_calls(query)
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Chroma client not available: {e}")
    except Exception as e:
        # chroma.search_calls returns [] when no index exists; any other runtime error becomes 503
        raise HTTPException(status_code=503, detail=f"Search service error: {e}")

    return {"query": query, "count": len(results), "results": results}



@app.get("/api/calls/{call_id}/audio")
def get_call_audio(call_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Return the original MP3 for a processed call.

    Resolution strategy:
    - prefer `call.audio_path` when it exists and points to a real file
    - if relative, resolve relative to the project root
    - fallback: data/audio/{call_id}.mp3
    """
    call = db.get(Call, call_id)
    if call is None or not call.processed:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found or not processed")

    # project root: two parents up from this file (backend/app/main.py -> backend -> project root)
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

    candidates: list[Path] = []

    if call.audio_path:
        p = Path(call.audio_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        candidates.append(p)

    # fallback location
    candidates.append(PROJECT_ROOT / "data" / "audio" / f"{call_id}.mp3")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return FileResponse(path=str(candidate), media_type="audio/mpeg", filename=f"{call_id}.mp3")

    raise HTTPException(status_code=404, detail=f"Audio file for call {call_id} not found (checked {len(candidates)} locations)")
