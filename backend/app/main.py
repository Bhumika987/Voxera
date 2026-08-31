import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Generator

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from fastapi import HTTPException
from pydantic import BaseModel
from app import auth
from app.auth import verify_token, verify_token_flexible
from app.database.schema import (
    get_session,
    Base,
    engine,
    Call,
    Customer,
    Agent,
    TranscriptSegment,
    AttentionReason,
    MoodEvent,
    ActionItem,
)
from pathlib import Path
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy import case

# chroma is imported lazily inside the endpoint to avoid import-time failures


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create any tables missing from an already-populated vexora.db (e.g.
    # action_items on first run after this feature landed). checkfirst=True is
    # the default, so existing tables and data are left untouched.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Voxera API", lifespan=lifespan)

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


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest) -> TokenResponse:
    """Exchange the manager username + password for an 8-hour JWT.

    Returns 401 if the credentials don't match the configured manager account.
    """
    if not auth.authenticate_manager(body.username, body.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return TokenResponse(access_token=auth.create_access_token(body.username))


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Return a simple health object including a dynamic count of calls
    stored in the database (from the `calls` table).
    """
    total_calls = db.query(Call).count()
    return {"status": "ok", "total_calls": total_calls}


@app.get("/api/dashboard/overview", dependencies=[Depends(verify_token)])
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



@app.get("/api/calls/{call_id}", dependencies=[Depends(verify_token)])
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



@app.get("/api/attention", dependencies=[Depends(verify_token)])
def list_attention(
    limit: int = 20,
    offset: int = 0,
    intent: str | None = None,
    final_mood: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Processed calls, ordered by attention_score descending, paginated with limit/offset.

    Two modes:
    - No `intent` / `final_mood` filter (default): only calls that qualify for
      manager attention — processed AND (attention_score >= 30 OR an attention
      reason contains manager/supervisor/escalat).
    - With a filter: every processed call matching that exact `intent` and/or
      `final_mood`, attention-qualified or not. This is what powers the
      dashboard's "click an intent" / "click a mood" drill-downs.

    - `limit` is clamped to 1..100 (default 20); `offset` is floored at 0.
    - `total` is the full count of matching calls (not just this page), so the
      caller can page through all of them.
    - `filtered` echoes whether a filter was applied; `intent` / `final_mood`
      echo the active filter values.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    intent = intent.strip() if intent else None
    final_mood = final_mood.strip().lower() if final_mood else None
    filtered = bool(intent) or bool(final_mood)

    manager_kw = ("manager", "supervisor", "escalat")
    or_clauses = [AttentionReason.reason.ilike(f"%{kw}%") for kw in manager_kw]

    # subquery of call_ids with manager-like reasons
    mgr_subq = db.query(AttentionReason.call_id).filter(or_(*or_clauses)).subquery()

    conditions = [Call.processed.is_(True)]
    if filtered:
        if intent:
            conditions.append(Call.intent == intent)
        if final_mood:
            conditions.append(func.lower(Call.final_mood) == final_mood)
    else:
        conditions.append(or_(Call.attention_score >= 30, Call.id.in_(mgr_subq)))

    total = db.query(func.count()).select_from(Call).filter(*conditions).scalar() or 0

    # id.asc() is a stable tiebreaker — many calls share a score, so without it
    # a row could appear on two pages (or none) as offset moves.
    calls = (
        db.query(Call)
        .filter(*conditions)
        .order_by(Call.attention_score.desc(), Call.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

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

    return {
        "count": len(out_calls),
        "total": total,
        "limit": limit,
        "offset": offset,
        "filtered": filtered,
        "intent": intent,
        "final_mood": final_mood,
        "calls": out_calls,
    }


@app.get("/api/intents", dependencies=[Depends(verify_token)])
def list_intents(db: Session = Depends(get_db)) -> dict:
    """Distinct free-text `intent` values across processed calls, with a call
    count each, most common first — used to populate the dashboard filter menu."""
    rows = (
        db.query(Call.intent, func.count(Call.id))
        .filter(Call.processed.is_(True), Call.intent.isnot(None), Call.intent != "")
        .group_by(Call.intent)
        .order_by(func.count(Call.id).desc(), Call.intent.asc())
        .all()
    )
    return {"count": len(rows), "intents": [{"intent": i, "count": c} for i, c in rows]}


@app.get("/api/customers", dependencies=[Depends(verify_token)])
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



@app.get("/api/customers/{customer_id}/calls", dependencies=[Depends(verify_token)])
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


@app.get("/api/agents", dependencies=[Depends(verify_token)])
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


@app.get("/api/trends", dependencies=[Depends(verify_token)])
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


SEARCH_MAX_RESULTS = 30


@app.get("/api/search", dependencies=[Depends(verify_token)])
def search(q: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Search processed calls, combining two passes:

    1. Structured (SQL LIKE) matches against agent name, customer name, intent
       text, and summary text — so "Elizabeth" returns every call that agent
       handled, and "pay a bill" returns every bill-payment call.
    2. Semantic (ChromaDB similarity over summaries) for meaning-based queries
       like "angry customer unresolved". Best-effort: an empty or unavailable
       index just contributes nothing instead of failing the request.

    Results are merged and de-duplicated by call_id, structured matches first
    (they're exact), then semantic matches by similarity. Each result carries a
    `match_type` of "agent" | "customer" | "intent" | "summary" | "semantic";
    `similarity_score` is null for structured matches.
    """
    if q is None:
        raise HTTPException(status_code=400, detail="Missing required query parameter 'q'")
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query 'q' must not be empty or whitespace")

    like = f"%{query}%"
    needle = query.lower()
    results: list[dict] = []
    seen: set[str] = set()

    def _row(call: Call, match_type: str) -> dict:
        return {
            "call_id": call.id,
            "customer_name": call.customer.name if call.customer else "",
            "agent_name": call.agent.name if call.agent else "",
            "intent": call.intent or "",
            "resolution": call.resolution or "unknown",
            "attention_score": call.attention_score if call.attention_score is not None else 0,
            "final_mood": call.final_mood or "unknown",
            "similarity_score": None,
            "match_type": match_type,
            "summary": call.summary or "",
        }

    structured = (
        db.query(Call)
        .join(Agent, Call.agent_id == Agent.id)
        .join(Customer, Call.customer_id == Customer.id)
        .filter(
            Call.processed.is_(True),
            or_(
                Agent.name.ilike(like),
                Customer.name.ilike(like),
                Call.intent.ilike(like),
                Call.summary.ilike(like),
            ),
        )
        .order_by(Call.attention_score.desc(), Call.started_at.desc())
        .limit(SEARCH_MAX_RESULTS)
        .all()
    )
    for call in structured:
        if call.id in seen:
            continue
        agent_name = (call.agent.name if call.agent else "").lower()
        customer_name = (call.customer.name if call.customer else "").lower()
        if needle in agent_name:
            match_type = "agent"
        elif needle in customer_name:
            match_type = "customer"
        elif call.intent and needle in call.intent.lower():
            match_type = "intent"
        else:
            match_type = "summary"
        results.append(_row(call, match_type))
        seen.add(call.id)

    if len(results) < SEARCH_MAX_RESULTS:
        try:
            # lazy import so a missing/broken chroma install can't take search down
            from app.services import chroma as chroma_service

            semantic_hits = [h for h in chroma_service.search_calls(query) if h["call_id"] not in seen]
        except Exception:
            semantic_hits = []  # semantic layer is optional — structured results still stand

        if semantic_hits:
            # keep only hits that are still real processed calls (chroma can lag the DB)
            valid_ids = {
                cid
                for (cid,) in db.query(Call.id).filter(
                    Call.id.in_([h["call_id"] for h in semantic_hits]),
                    Call.processed.is_(True),
                )
            }
            for hit in semantic_hits:
                if hit["call_id"] not in valid_ids or hit["call_id"] in seen:
                    continue
                results.append({**hit, "match_type": "semantic"})
                seen.add(hit["call_id"])
                if len(results) >= SEARCH_MAX_RESULTS:
                    break

    results = results[:SEARCH_MAX_RESULTS]
    return {"query": query, "count": len(results), "results": results}



class AskRequest(BaseModel):
    question: str


@app.post("/api/ask", dependencies=[Depends(verify_token)])
def ask(body: AskRequest, db: Session = Depends(get_db)) -> dict:
    """Answer a natural-language question about the call data.

    The LLM (Groq) is given a small fixed set of read-only tools over this
    database — it plans which to call, gets real numbers back, and writes an
    answer over them, citing the call_ids it used as evidence. It cannot run
    arbitrary SQL or invent a statistic. See app/services/ask.py.

    - 400 if the question is empty.
    - 503 if the LLM provider is unreachable or GROQ_API_KEY is unset.
    """
    from app.services import ask as ask_service

    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="Question is too long (max 500 characters)")

    try:
        return ask_service.answer_question(question, db)
    except ask_service.AskError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/calls/{call_id}/audio", dependencies=[Depends(verify_token_flexible)])
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


# --- Manager Action Center ------------------------------------------------

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


class ActionItemUpdate(BaseModel):
    status: str | None = None
    assigned_to: str | None = None
    note: str | None = None


def _serialize_action_item(item: ActionItem) -> dict:
    try:
        entity_ids = json.loads(item.entity_ids or "[]")
    except (TypeError, ValueError):
        entity_ids = []
    return {
        "id": item.id,
        "source_key": item.source_key,
        "rule_id": item.rule_id,
        "title": item.title,
        "description": item.description,
        "priority": item.priority,
        "group_label": item.group_label,
        "metric_count": item.metric_count,
        "entity_type": item.entity_type,
        "entity_count": len(entity_ids),
        "status": item.status,
        "assigned_to": item.assigned_to,
        "note": item.note,
        "auto_resolved": item.auto_resolved,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@app.get("/api/actions", dependencies=[Depends(verify_token)])
def list_actions(status: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Return the Action Center task list, regenerating it from the current data first.

    Generation is idempotent and preserves manager-set status / assignee / note
    (see app/services/actions.py). If it fails for any reason the stored list is
    still returned — the dashboard degrades rather than erroring.

    - `status` optionally filters to one of open|investigating|resolved|dismissed.
    - `actions` are ordered by priority (high→low) then by metric_count desc.
    - `status_counts` / `open_total` summarise the whole list, ignoring `status`.
    """
    from app.services import actions as actions_service

    try:
        actions_service.generate(db)
    except Exception:
        db.rollback()

    query = db.query(ActionItem)
    if status:
        query = query.filter(ActionItem.status == status)
    items = query.all()
    items.sort(key=lambda i: (_PRIORITY_RANK.get(i.priority, 3), -i.metric_count, i.id))

    counts: dict = {}
    for row_status, cnt in db.query(ActionItem.status, func.count()).group_by(ActionItem.status):
        counts[row_status] = cnt
    for expected in ("open", "investigating", "resolved", "dismissed"):
        counts.setdefault(expected, 0)

    return {
        "count": len(items),
        "status_counts": counts,
        "open_total": counts["open"] + counts["investigating"],
        "actions": [_serialize_action_item(i) for i in items],
    }


@app.post("/api/actions/generate", dependencies=[Depends(verify_token)])
def regenerate_actions(db: Session = Depends(get_db)) -> dict:
    """Force a regeneration pass and return what changed (created / updated / auto_resolved)."""
    from app.services import actions as actions_service

    return actions_service.generate(db)


@app.get("/api/actions/{action_id}", dependencies=[Depends(verify_token)])
def get_action(action_id: int, db: Session = Depends(get_db)) -> dict:
    """One action item plus its frozen cohort resolved to displayable rows.

    `entities` is the list of calls (or customers) captured when the task was
    created, in the task's own order; rows that no longer exist are skipped.
    Returns 404 if the action id is unknown.
    """
    item = db.get(ActionItem, action_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")

    try:
        entity_ids = json.loads(item.entity_ids or "[]")
    except (TypeError, ValueError):
        entity_ids = []

    out = _serialize_action_item(item)
    out["entities"] = []

    if item.entity_type == "call":
        calls = {c.id: c for c in db.query(Call).filter(Call.id.in_(entity_ids)).all()}
        for cid in entity_ids:
            c = calls.get(cid)
            if c is None:
                continue
            out["entities"].append(
                {
                    "type": "call",
                    "call_id": c.id,
                    "customer_name": c.customer.name if c.customer else None,
                    "agent_name": c.agent.name if c.agent else None,
                    "intent": c.intent,
                    "resolution": c.resolution,
                    "final_mood": c.final_mood,
                    "attention_score": c.attention_score,
                    "started_at": c.started_at.isoformat() if c.started_at else None,
                }
            )
    elif item.entity_type == "customer":
        wanted = [int(x) for x in entity_ids]
        customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(wanted)).all()}
        for cust_id in wanted:
            cust = customers.get(cust_id)
            if cust is None:
                continue
            calls = db.query(Call).filter(Call.customer_id == cust_id, Call.processed.is_(True)).all()
            last_call = max((c.started_at for c in calls if c.started_at), default=None)
            out["entities"].append(
                {
                    "type": "customer",
                    "customer_id": cust.id,
                    "name": cust.name,
                    "total_calls": len(calls),
                    "unresolved_calls": sum(1 for c in calls if c.resolution == "unresolved"),
                    "last_call_at": last_call.isoformat() if last_call else None,
                }
            )

    return out


@app.patch("/api/actions/{action_id}", dependencies=[Depends(verify_token)])
def update_action(action_id: int, body: ActionItemUpdate, db: Session = Depends(get_db)) -> dict:
    """Apply a manager action to one task: change status, (re)assign, or set a note.

    A manual status change is authoritative — it clears the `auto_resolved` flag so
    the next generation pass won't treat the row as system-managed. Passing an
    empty string for `assigned_to` / `note` clears that field.

    - 404 if the action id is unknown.
    - 422 if `status` is not one of open|investigating|resolved|dismissed.
    """
    from app.services import actions as actions_service

    item = db.get(ActionItem, action_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")

    if body.status is not None:
        if body.status not in actions_service.VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{body.status}'. Expected one of {actions_service.VALID_STATUSES}.",
            )
        item.status = body.status
        item.auto_resolved = False
    if body.assigned_to is not None:
        item.assigned_to = body.assigned_to.strip() or None
    if body.note is not None:
        item.note = body.note.strip() or None

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _serialize_action_item(item)
