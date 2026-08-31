"""
"Ask Voxera" — natural-language questions answered over the call-centre data.

This is NOT free-form text-to-SQL. The LLM is given a small, fixed set of
read-only tools (aggregate / find_calls / semantic_search / get_call), each
backed by a parameterised SQLAlchemy query with a strict allowlist of
group-by keys and filter fields. The model plans which tools to call, gets
*real* numbers back, and composes an answer over them — so it can't invent a
statistic or a column name, and every call it cites is a real call_id the
frontend can link to (mirrors the evidence-first rule the rest of the app
follows: `analyze.py` verifies every evidence segment id, so do we).

Provider: Groq, same model chain as `analyze.py` (`openai/gpt-oss-120b` then
`openai/gpt-oss-20b`), both OpenAI-compatible so tool-calling works via the
standard `tools=` / `tool_calls` shape. No Ollama tier here — unlike the
batch pipeline this is an interactive request, so if Groq is down we return
503 rather than block for ~140s on local CPU inference.

Public entry point:
    answer_question(question: str, db: Session) -> dict
        {
          "answer": str,
          "tool_calls": [{"tool": str, "arguments": dict, "result_preview": str}, ...],
          "evidence_call_ids": [str, ...],   # de-duped, in first-seen order
          "model_used": str,
        }
    Raises AskError (LLM unavailable / misconfigured) — the route maps it to 503.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import groq
from dotenv import load_dotenv
from sqlalchemy import case, exists, func
from sqlalchemy.orm import Session

from app.database.schema import Agent, AttentionReason, Call, Customer, MoodEvent, TranscriptSegment

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

GROQ_MODEL_CHAIN = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
MAX_TOOL_ROUNDS = 5          # how many assistant<->tool exchanges before we force a final answer
MAX_ROWS = 25                # cap on rows any single tool returns
RESULT_PREVIEW_CHARS = 600   # how much of each tool result we keep in the returned trace

# Mirrors analyze.py's closed vocabularies so the model can't filter on a value
# that will never match.
MOOD_VALUES = ("happy", "neutral", "confused", "frustrated", "angry")
NEGATIVE_MOODS = ("frustrated", "angry")
NON_NEGATIVE_MOODS = ("happy", "neutral", "confused")
RESOLUTION_VALUES = ("resolved", "unresolved", "unknown")
INTENT_CATEGORIES = (
    "LOST_CARD", "DUPLICATE_CHARGE", "PASSWORD_RESET", "TRANSFER_MONEY",
    "BALANCE_CHECK", "ACCOUNT_CLOSURE", "BILL_PAYMENT", "BRANCH_INQUIRY",
    "APPOINTMENT_SCHEDULING", "OTHER",
)
GROUP_BY_KEYS = (
    "intent", "intent_category", "agent", "customer",
    "final_mood", "initial_mood", "resolution", "day",
)

_groq_client: groq.Groq | None = None


class AskError(RuntimeError):
    """LLM is unreachable or misconfigured — nothing the caller can fix by retrying differently."""


def _get_groq_client() -> groq.Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise AskError("GROQ_API_KEY is not set. Add it to backend/.env (see backend/.env.example).")
        _groq_client = groq.Groq(api_key=api_key)
    return _groq_client


# --------------------------------------------------------------------------- #
# Filters — one shared allowlist used by both `aggregate` and `find_calls`.
# Anything not listed here is silently ignored rather than trusted.
# --------------------------------------------------------------------------- #

def _apply_filters(query, filters: dict[str, Any] | None):
    """Return `query` with the recognised filters ANDed on. Unknown keys are ignored."""
    if not filters:
        return query
    f = filters

    if f.get("resolution") in RESOLUTION_VALUES:
        query = query.filter(Call.resolution == f["resolution"])
    if f.get("final_mood") in MOOD_VALUES:
        query = query.filter(func.lower(Call.final_mood) == f["final_mood"])
    if f.get("initial_mood") in MOOD_VALUES:
        query = query.filter(func.lower(Call.initial_mood) == f["initial_mood"])
    if f.get("intent_category") in INTENT_CATEGORIES:
        query = query.filter(Call.intent_category == f["intent_category"])
    if isinstance(f.get("intent_contains"), str) and f["intent_contains"].strip():
        query = query.filter(Call.intent.ilike(f"%{f['intent_contains'].strip()}%"))
    if isinstance(f.get("agent_name"), str) and f["agent_name"].strip():
        query = query.filter(Agent.name.ilike(f["agent_name"].strip()))
    if isinstance(f.get("customer_name"), str) and f["customer_name"].strip():
        query = query.filter(Customer.name.ilike(f["customer_name"].strip()))
    if isinstance(f.get("min_attention_score"), (int, float)):
        query = query.filter(Call.attention_score >= f["min_attention_score"])

    # "customer started calm and ended upset" — the mood-shift pattern the app cares about
    if f.get("became_negative") is True:
        query = query.filter(
            func.lower(Call.initial_mood).in_(NON_NEGATIVE_MOODS),
            func.lower(Call.final_mood).in_(NEGATIVE_MOODS),
        )
    # "mood changed to angry at some point mid-call" (a recorded MoodEvent, not just endpoints)
    if f.get("mood_shifted_to") in MOOD_VALUES:
        query = query.filter(
            exists().where(
                (MoodEvent.call_id == Call.id)
                & (func.lower(MoodEvent.mood_after) == f["mood_shifted_to"])
            )
        )
    return query


def _needs_agent_join(filters: dict | None) -> bool:
    return bool(filters and isinstance(filters.get("agent_name"), str) and filters["agent_name"].strip())


def _needs_customer_join(filters: dict | None) -> bool:
    return bool(filters and isinstance(filters.get("customer_name"), str) and filters["customer_name"].strip())


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

def tool_aggregate(db: Session, group_by: str, filters: dict | None = None) -> dict:
    """Counts and averages over processed calls, grouped by one dimension."""
    if group_by not in GROUP_BY_KEYS:
        return {"error": f"group_by must be one of {list(GROUP_BY_KEYS)}"}

    group_col = {
        "intent": Call.intent,
        "intent_category": Call.intent_category,
        "agent": Agent.name,
        "customer": Customer.name,
        "final_mood": Call.final_mood,
        "initial_mood": Call.initial_mood,
        "resolution": Call.resolution,
        "day": func.date(Call.started_at),
    }[group_by]

    unresolved_c = func.sum(case((Call.resolution == "unresolved", 1), else_=0))
    resolved_c = func.sum(case((Call.resolution == "resolved", 1), else_=0))

    q = db.query(
        group_col.label("group"),
        func.count(Call.id).label("total_calls"),
        resolved_c.label("resolved"),
        unresolved_c.label("unresolved"),
        func.round(func.avg(Call.attention_score), 1).label("avg_attention_score"),
    ).filter(Call.processed.is_(True))

    if group_by == "agent" or _needs_agent_join(filters):
        q = q.join(Agent, Call.agent_id == Agent.id)
    if group_by == "customer" or _needs_customer_join(filters):
        q = q.join(Customer, Call.customer_id == Customer.id)

    q = _apply_filters(q, filters)
    q = q.group_by(group_col).order_by(func.count(Call.id).desc()).limit(MAX_ROWS)

    rows = []
    for r in q.all():
        total = int(r.total_calls or 0)
        unresolved = int(r.unresolved or 0)
        rows.append({
            "group": r.group if r.group is not None else "unknown",
            "total_calls": total,
            "resolved": int(r.resolved or 0),
            "unresolved": unresolved,
            "unresolved_rate_pct": round(100.0 * unresolved / total, 1) if total else 0.0,
            "avg_attention_score": float(r.avg_attention_score) if r.avg_attention_score is not None else 0.0,
        })
    return {"group_by": group_by, "filters": filters or {}, "row_count": len(rows), "rows": rows}


def tool_find_calls(db: Session, filters: dict | None = None, limit: int = 10, order_by: str = "attention_score") -> dict:
    """Individual processed calls matching the filters, highest attention first by default."""
    limit = max(1, min(int(limit or 10), MAX_ROWS))

    q = (
        db.query(Call)
        .join(Agent, Call.agent_id == Agent.id)
        .join(Customer, Call.customer_id == Customer.id)
        .filter(Call.processed.is_(True))
    )
    q = _apply_filters(q, filters)

    order_col = {
        "attention_score": Call.attention_score.desc(),
        "duration": Call.duration_seconds.desc(),
        "recent": Call.started_at.desc(),
    }.get(order_by, Call.attention_score.desc())
    q = q.order_by(order_col, Call.id.asc()).limit(limit)

    calls = q.all()
    rows = [{
        "call_id": c.id,
        "customer_name": c.customer.name if c.customer else None,
        "agent_name": c.agent.name if c.agent else None,
        "intent": c.intent,
        "intent_category": c.intent_category,
        "resolution": c.resolution,
        "initial_mood": c.initial_mood,
        "final_mood": c.final_mood,
        "attention_score": c.attention_score,
        "duration_seconds": round(c.duration_seconds, 1) if c.duration_seconds is not None else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "summary": c.summary,
    } for c in calls]
    return {"filters": filters or {}, "order_by": order_by, "row_count": len(rows), "calls": rows}


def tool_semantic_search(db: Session, query: str, limit: int = 6) -> dict:
    """Meaning-based search over call summaries (ChromaDB). Use for themes/phrasing
    that aren't a structured field, e.g. 'customer felt talked down to'."""
    limit = max(1, min(int(limit or 6), 10))
    try:
        from app.services import chroma as chroma_service

        hits = chroma_service.search_calls(query, n_results=limit)
    except Exception as e:  # noqa: BLE001 — semantic layer is optional, never fatal to a question
        return {"query": query, "error": f"semantic search unavailable: {e}", "row_count": 0, "calls": []}

    # keep only hits that are still real processed calls (chroma can lag the DB)
    ids = [h["call_id"] for h in hits]
    valid = {cid for (cid,) in db.query(Call.id).filter(Call.id.in_(ids), Call.processed.is_(True))}
    rows = [{
        "call_id": h["call_id"],
        "customer_name": h.get("customer_name"),
        "agent_name": h.get("agent_name"),
        "intent": h.get("intent"),
        "resolution": h.get("resolution"),
        "attention_score": h.get("attention_score"),
        "similarity": h.get("similarity_score"),
        "summary": h.get("summary"),
    } for h in hits if h["call_id"] in valid]
    return {"query": query, "row_count": len(rows), "calls": rows}


def tool_get_call(db: Session, call_id: str) -> dict:
    """Full detail for one call: summary, moods, the deterministic attention
    reasons (with their evidence quotes), and the mood-shift transitions."""
    call = db.get(Call, call_id)
    if call is None or not call.processed:
        return {"error": f"call {call_id} not found or not processed"}

    seg_text = {
        s.segment_id: s.text
        for s in db.query(TranscriptSegment).filter(TranscriptSegment.call_id == call_id)
    }
    reasons = db.query(AttentionReason).filter(AttentionReason.call_id == call_id).all()
    moods = db.query(MoodEvent).filter(MoodEvent.call_id == call_id).order_by(MoodEvent.timestamp).all()

    return {
        "call_id": call.id,
        "customer_name": call.customer.name if call.customer else None,
        "agent_name": call.agent.name if call.agent else None,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "duration_seconds": round(call.duration_seconds, 1) if call.duration_seconds is not None else None,
        "intent": call.intent,
        "intent_category": call.intent_category,
        "resolution": call.resolution,
        "summary": call.summary,
        "initial_mood": call.initial_mood,
        "final_mood": call.final_mood,
        "attention_score": call.attention_score,
        "attention_reasons": [{
            "reason": r.reason,
            "points": r.points,
            "evidence": seg_text.get(r.evidence_segment_id) if r.evidence_segment_id else None,
        } for r in reasons],
        "mood_events": [{
            "at_seconds": round(m.timestamp, 1),
            "from": m.mood_before,
            "to": m.mood_after,
            "evidence": seg_text.get(m.segment_id),
        } for m in moods],
    }


TOOL_DISPATCH = {
    "aggregate": tool_aggregate,
    "find_calls": tool_find_calls,
    "semantic_search": tool_semantic_search,
    "get_call": tool_get_call,
}

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": (
                "Counts, resolution rates and average attention score over processed calls, "
                "grouped by one dimension. Use this for any 'how many / which X has the most / "
                "highest rate' question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "group_by": {"type": "string", "enum": list(GROUP_BY_KEYS)},
                    "filters": {"type": "object", "description": "Optional. See the filter fields listed in the system prompt."},
                },
                "required": ["group_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_calls",
            "description": "List individual calls matching structured filters. Returns call_id, moods, resolution, attention score and summary. Use to pull concrete examples / evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filters": {"type": "object"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    "order_by": {"type": "string", "enum": ["attention_score", "duration", "recent"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Meaning-based search over call summaries for themes that are not a structured field (tone, phrasing, specific complaints). Returns matching call_ids.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_call",
            "description": "Full detail for one call_id: summary, mood transitions, and the attention-score reasons with their transcript evidence quotes.",
            "parameters": {
                "type": "object",
                "properties": {"call_id": {"type": "string"}},
                "required": ["call_id"],
            },
        },
    },
]


SYSTEM_PROMPT = f"""You are Voxera's analyst assistant. A call-centre manager asks you questions about \
a fixed dataset of 1,441 recorded bank customer-support calls. You answer ONLY by calling the \
provided tools and reasoning over what they return.

Hard rules:
- Never state a number, count, rate or ranking that did not come back from a tool call this turn. \
If you didn't measure it, don't claim it.
- When you reference specific calls as evidence, include their call_id values in your answer.
- Keep the answer to 2-5 sentences. Lead with the direct answer, then the supporting detail. \
No preamble, no "based on the data".
- If the tools return nothing relevant, say so plainly rather than guessing.

Dataset facts you must respect:
- The calls span only four dates in 2020: 2020-03-15, 2020-05-30, 2020-06-01, 2020-06-02. \
There is no "today", "this week" or "recently" — if asked about trends over time, either use \
group_by="day" and describe those four buckets, or explain the data isn't time-current and \
answer for the whole dataset.
- There are only 100 distinct customer NAMES across all 1,441 calls (~14x reuse), and identity \
is name-only, so per-customer conclusions are weak — caveat them or prefer agent / intent / mood cuts.
- resolution is one of: {", ".join(RESOLUTION_VALUES)}. mood is one of: {", ".join(MOOD_VALUES)}. \
intent_category is one of: {", ".join(INTENT_CATEGORIES)}. intent is also stored as free text — \
use filters.intent_contains for substring matching on it.
- When describing "negative" / "unhappy" / "bad" moods, use EXACTLY frustrated + angry (this is \
how the dashboard's "ended negative" figure is defined). "confused" is NOT negative — count and \
report it separately, never fold it in with frustrated. Don't invent your own mood groupings.

Filter fields accepted by aggregate.filters and find_calls.filters (all optional, combined with AND):
  resolution, final_mood, initial_mood, intent_category, intent_contains (substring),
  agent_name (exact, case-insensitive), customer_name, min_attention_score (number),
  became_negative (bool: started non-negative, ended frustrated/angry),
  mood_shifted_to (mood: had a mid-call mood change to this mood).
"""


def _truncate(text: str, limit: int = RESULT_PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


def _run_chain(messages: list[dict], db: Session) -> tuple[str, list[dict], list[str], str]:
    """Drive the tool-calling loop against the Groq model chain. Returns
    (answer_text, tool_trace, evidence_call_ids, model_used)."""
    client = _get_groq_client()
    last_error: Exception | None = None

    for model in GROQ_MODEL_CHAIN:
        convo = list(messages)
        tool_trace: list[dict] = []
        evidence_ids: list[str] = []
        seen_ids: set[str] = set()

        try:
            for round_i in range(MAX_TOOL_ROUNDS):
                # On the final round, drop the tools entirely so the model is
                # forced to answer in prose (more portable than tool_choice="none").
                force_final = round_i == MAX_TOOL_ROUNDS - 1
                kwargs = {} if force_final else {"tools": TOOL_SCHEMA, "tool_choice": "auto"}
                completion = client.chat.completions.create(
                    model=model,
                    messages=convo,
                    temperature=0.1,
                    max_tokens=1200,
                    **kwargs,
                )
                msg = completion.choices[0].message
                tool_calls = msg.tool_calls or []

                if not tool_calls:
                    return (msg.content or "").strip(), tool_trace, evidence_ids, model

                convo.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    } for tc in tool_calls],
                })

                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    fn = TOOL_DISPATCH.get(name)
                    if fn is None:
                        result = {"error": f"unknown tool {name}"}
                    else:
                        try:
                            result = fn(db, **args)
                        except TypeError as e:
                            result = {"error": f"bad arguments for {name}: {e}"}
                        except Exception as e:  # noqa: BLE001 — a bad tool call shouldn't 500 the request
                            result = {"error": f"{name} failed: {e}"}

                    for row in (result.get("rows") or []) + (result.get("calls") or []):
                        cid = row.get("call_id")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            evidence_ids.append(cid)
                    if result.get("call_id") and result["call_id"] not in seen_ids:
                        seen_ids.add(result["call_id"])
                        evidence_ids.append(result["call_id"])

                    result_json = json.dumps(result, default=str)
                    tool_trace.append({
                        "tool": name,
                        "arguments": args,
                        "result_preview": _truncate(result_json),
                    })
                    convo.append({"role": "tool", "tool_call_id": tc.id, "content": result_json})

            # Loop exhausted without a plain-text answer (shouldn't happen: last round is tool_choice="none")
            return (
                "I wasn't able to converge on an answer for that one — try narrowing the question.",
                tool_trace, evidence_ids, model,
            )

        except groq.RateLimitError as e:
            last_error = e
            continue  # exhausted quota on this model — try the next
        except groq.NotFoundError as e:
            last_error = e
            continue
        except groq.APIStatusError as e:
            last_error = e
            if e.status_code and e.status_code < 500:
                break  # a real client error will repeat on the next model too
            continue
        except groq.APIConnectionError as e:
            last_error = e
            continue

    raise AskError(f"Groq model chain exhausted: {last_error}")


def answer_question(question: str, db: Session) -> dict:
    """Answer one natural-language question about the call data. See module docstring."""
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    answer, tool_trace, evidence_ids, model_used = _run_chain(messages, db)

    return {
        "answer": answer,
        "tool_calls": [{"tool": t["tool"], "arguments": t["arguments"], "result_preview": t["result_preview"]} for t in tool_trace],
        "evidence_call_ids": evidence_ids,
        "model_used": model_used,
    }
