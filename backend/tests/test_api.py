import sys
import types
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import bcrypt

from app.main import app, get_db
from app import auth
from app.auth import verify_token, verify_token_flexible
from app.database import schema
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="module")
def test_db_session():
    """Create a shared in-memory SQLite DB using StaticPool and populate minimal test data.

    Using `sqlite://` with `StaticPool` ensures the same connection is reused across
    threads used by TestClient so the in-memory DB is shared.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # create tables on the shared engine
    schema.Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # insert fixtures using a session from SessionLocal
    session = SessionLocal()
    try:
        cust = schema.Customer(name="Test Customer")
        agent = schema.Agent(name="Test Agent")
        session.add_all([cust, agent])
        session.flush()

        call = schema.Call(
            id="testcall1",
            customer_id=cust.id,
            agent_id=agent.id,
            started_at=datetime.utcnow(),
            duration_seconds=12.3,
            audio_path="data/audio/testcall1.mp3",
            intent="Check balance",
            intent_evidence_segment_id="seg_1",
            resolution="resolved",
            summary="Short summary",
            initial_mood="neutral",
            final_mood="neutral",
            attention_score=35,
            processed=True,
        )
        session.add(call)
        session.flush()

        seg = schema.TranscriptSegment(
            call_id=call.id,
            segment_id="seg_1",
            speaker="customer",
            start_time=0.0,
            end_time=3.0,
            text="I need help checking my balance",
        )
        ar = schema.AttentionReason(call_id=call.id, reason="manager please", points=40, evidence_segment_id="seg_1")
        me = schema.MoodEvent(call_id=call.id, timestamp=2.0, mood_before="neutral", mood_after="frustrated", segment_id="seg_1")
        session.add_all([seg, ar, me])
        session.commit()
    finally:
        session.close()

    # yield the SessionLocal factory so override can create per-request sessions
    try:
        yield SessionLocal
    finally:
        # drop all tables after tests to clean up
        schema.Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def override_dependency(test_db_session):
    """Override FastAPI DB dependency to use the shared in-memory SessionLocal.

    Also stubs out the JWT dependency so the existing endpoint tests don't each
    have to mint and pass a token — the dedicated auth tests below exercise the
    real token path (and the real 401).
    """

    def _get_test_db():
        db = test_db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[verify_token] = lambda: "test-manager"
    app.dependency_overrides[verify_token_flexible] = lambda: "test-manager"
    yield
    app.dependency_overrides.clear()


# Known manager credentials for the auth tests (independent of the real .env).
_TEST_MANAGER_PW = "s3cret-pw"


@pytest.fixture
def real_auth(monkeypatch):
    """Restore the genuine JWT dependency and point auth at a known test account."""
    app.dependency_overrides.pop(verify_token, None)
    app.dependency_overrides.pop(verify_token_flexible, None)
    monkeypatch.setattr(auth, "MANAGER_USERNAME", "manager")
    monkeypatch.setattr(
        auth,
        "MANAGER_PASSWORD_HASH",
        bcrypt.hashpw(_TEST_MANAGER_PW.encode(), bcrypt.gensalt(rounds=4)).decode(),
    )
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "test-secret")
    yield


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert isinstance(data.get("total_calls"), int)


def test_dashboard_overview(client):
    resp = client.get("/api/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    for k in ("total_calls", "resolved", "unresolved", "resolution_rate", "needs_attention", "mood_distribution"):
        assert k in data


def test_list_customers_and_customer_calls(client):
    resp = client.get("/api/customers")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("count") == 1
    cust = data["customers"][0]
    assert cust["name"] == "Test Customer"

    # valid customer
    cust_id = cust["customer_id"]
    resp2 = client.get(f"/api/customers/{cust_id}/calls")
    assert resp2.status_code == 200
    cdata = resp2.json()
    assert cdata.get("customer_id") == cust_id

    # nonexistent customer
    resp3 = client.get("/api/customers/9999/calls")
    assert resp3.status_code == 404


def test_agents_and_trends(client):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    ad = resp.json()
    assert "count" in ad and "agents" in ad

    resp2 = client.get("/api/trends")
    assert resp2.status_code == 200
    td = resp2.json()
    assert "count" in td and "trends" in td


def test_get_call_and_audio_404(client):
    # existing call
    resp = client.get("/api/calls/testcall1")
    assert resp.status_code == 200
    cd = resp.json()
    assert cd.get("call_id") == "testcall1"
    assert isinstance(cd.get("transcript"), list)
    assert isinstance(cd.get("attention_reasons"), list)

    # nonexistent call
    resp2 = client.get("/api/calls/nope")
    assert resp2.status_code == 404

    # audio should 404 (file not present in test environment)
    resp3 = client.get("/api/calls/testcall1/audio")
    assert resp3.status_code == 404


def test_attention_and_search(client, monkeypatch):
    resp = client.get("/api/attention")
    assert resp.status_code == 200
    ad = resp.json()
    assert "count" in ad and "calls" in ad

    # Prepare a fake chroma module so the endpoint can import it lazily
    fake = types.ModuleType("app.services.chroma")
    fake.search_calls = lambda q: [{"call_id": "testcall1", "score": 0.9, "summary": "fake"}]
    monkeypatch.setitem(sys.modules, "app.services.chroma", fake)

    # valid query
    resp2 = client.get("/api/search?q=balance")
    assert resp2.status_code == 200
    sd = resp2.json()
    assert sd.get("query") == "balance"
    assert sd.get("count") == 1

    # whitespace-only query -> 400
    resp3 = client.get("/api/search?q=   ")
    assert resp3.status_code == 400


def test_attention_pagination(client):
    resp = client.get("/api/attention")
    data = resp.json()
    assert data["total"] == 1
    assert data["limit"] == 20 and data["offset"] == 0
    assert len(data["calls"]) == 1

    # offset past the end -> empty page, but total still reports the true count
    data2 = client.get("/api/attention?limit=5&offset=50").json()
    assert data2["total"] == 1
    assert data2["limit"] == 5 and data2["offset"] == 50
    assert data2["calls"] == []

    # limit is clamped to <= 100
    assert client.get("/api/attention?limit=9999").json()["limit"] == 100


def test_intents_list(client):
    data = client.get("/api/intents").json()
    assert data["count"] == 1
    assert data["intents"] == [{"intent": "Check balance", "count": 1}]


def test_attention_intent_and_mood_filter(client):
    # filter by exact intent -> filtered mode, matching call returned
    data = client.get("/api/attention", params={"intent": "Check balance"}).json()
    assert data["filtered"] is True
    assert data["intent"] == "Check balance"
    assert data["total"] == 1 and data["calls"][0]["call_id"] == "testcall1"

    # non-matching intent -> empty, still filtered
    empty = client.get("/api/attention", params={"intent": "Nope"}).json()
    assert empty["filtered"] is True and empty["total"] == 0

    # mood filter is case-insensitive
    mood = client.get("/api/attention", params={"final_mood": "NEUTRAL"}).json()
    assert mood["filtered"] is True and mood["total"] == 1

    happy = client.get("/api/attention", params={"final_mood": "happy"}).json()
    assert happy["total"] == 0


def test_search_matches_agent_and_intent(client):
    by_agent = client.get("/api/search", params={"q": "Test Agent"}).json()
    assert by_agent["count"] == 1
    assert by_agent["results"][0]["call_id"] == "testcall1"
    assert by_agent["results"][0]["match_type"] == "agent"
    assert by_agent["results"][0]["similarity_score"] is None

    by_intent = client.get("/api/search", params={"q": "balance"}).json()
    assert by_intent["results"][0]["match_type"] == "intent"

    assert client.get("/api/search", params={"q": "zzz-no-such-thing"}).json()["count"] == 0


def test_ask_endpoint_returns_answer(client, monkeypatch):
    """POST /api/ask delegates to ask.answer_question and passes its result through."""
    from app.services import ask as ask_service

    canned = {
        "answer": "Bill payment has the highest unresolved rate at 18.4%.",
        "tool_calls": [{"tool": "aggregate", "arguments": {"group_by": "intent_category"}, "result_preview": "{...}"}],
        "evidence_call_ids": ["testcall1"],
        "model_used": "openai/gpt-oss-120b",
    }
    monkeypatch.setattr(ask_service, "answer_question", lambda q, db: canned)

    resp = client.post("/api/ask", json={"question": "Which issue has the highest unresolved rate?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"].startswith("Bill payment")
    assert data["evidence_call_ids"] == ["testcall1"]
    assert data["tool_calls"][0]["tool"] == "aggregate"


def test_ask_empty_question_is_400(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code == 400


def test_ask_llm_unavailable_is_503(client, monkeypatch):
    from app.services import ask as ask_service

    def _boom(q, db):
        raise ask_service.AskError("GROQ_API_KEY is not set.")

    monkeypatch.setattr(ask_service, "answer_question", _boom)
    resp = client.post("/api/ask", json={"question": "anything"})
    assert resp.status_code == 503


def test_ask_tools_run_against_db(test_db_session):
    """The read-only tool functions work directly against a session (no LLM)."""
    from app.services import ask as ask_service

    db = test_db_session()
    try:
        agg = ask_service.tool_aggregate(db, "resolution")
        assert agg["row_count"] == 1
        assert agg["rows"][0] == {
            "group": "resolved",
            "total_calls": 1,
            "resolved": 1,
            "unresolved": 0,
            "unresolved_rate_pct": 0.0,
            "avg_attention_score": 35.0,
        }

        found = ask_service.tool_find_calls(db, {"resolution": "resolved"}, limit=5)
        assert [c["call_id"] for c in found["calls"]] == ["testcall1"]

        # mood_shifted_to matches the fixture's neutral->frustrated MoodEvent
        shifted = ask_service.tool_find_calls(db, {"mood_shifted_to": "frustrated"})
        assert [c["call_id"] for c in shifted["calls"]] == ["testcall1"]

        detail = ask_service.tool_get_call(db, "testcall1")
        assert detail["resolution"] == "resolved"
        assert detail["attention_reasons"][0]["evidence"] == "I need help checking my balance"

        assert ask_service.tool_get_call(db, "nope")["error"]
        assert ask_service.tool_aggregate(db, "bogus")["error"]
    finally:
        db.close()


def _isolated_session():
    """A fresh in-memory DB with every schema table — for tests that need to seed
    rule-triggering data without disturbing the shared module fixture's counts."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    schema.Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng, autoflush=False, autocommit=False)


def _seed_unresolved_calls(SessionLocal, n, category="BILL_PAYMENT"):
    session = SessionLocal()
    try:
        cust = schema.Customer(name="Repeat Customer")
        agent = schema.Agent(name="Agent Smith")
        session.add_all([cust, agent])
        session.flush()
        for i in range(n):
            session.add(
                schema.Call(
                    id=f"unres{i}",
                    customer_id=cust.id,
                    agent_id=agent.id,
                    started_at=datetime.utcnow(),
                    duration_seconds=60.0,
                    audio_path=f"data/audio/unres{i}.mp3",
                    intent="refund request",
                    intent_category=category,
                    resolution="unresolved",
                    final_mood="frustrated",
                    attention_score=40,
                    processed=True,
                )
            )
        session.commit()
    finally:
        session.close()


def test_actions_generate_upsert_and_preserve_status():
    from app.services import actions as actions_service

    SessionLocal = _isolated_session()
    _seed_unresolved_calls(SessionLocal, 12)

    db = SessionLocal()
    try:
        summary = actions_service.generate(db)
        assert summary["created"] >= 1

        item = (
            db.query(schema.ActionItem)
            .filter(schema.ActionItem.source_key == "unresolved_category:BILL_PAYMENT")
            .one()
        )
        assert item.metric_count == 12
        assert item.priority == "medium"  # 12 -> medium (>=10), not high (>=20)
        assert item.status == "open"

        # a manager takes ownership; regeneration must not stomp it
        item.status = "investigating"
        db.commit()
        actions_service.generate(db)
        db.refresh(item)
        assert item.status == "investigating"
    finally:
        db.close()


def test_actions_auto_resolve_when_rule_stops_firing():
    from app.services import actions as actions_service

    SessionLocal = _isolated_session()
    _seed_unresolved_calls(SessionLocal, 12)

    db = SessionLocal()
    try:
        actions_service.generate(db)
        # every unresolved call becomes resolved -> the category rule stops firing
        db.query(schema.Call).update({schema.Call.resolution: "resolved"})
        db.commit()
        summary = actions_service.generate(db)
        assert summary["auto_resolved"] >= 1

        item = (
            db.query(schema.ActionItem)
            .filter(schema.ActionItem.source_key == "unresolved_category:BILL_PAYMENT")
            .one()
        )
        assert item.status == "resolved"
        assert item.auto_resolved is True
    finally:
        db.close()


def test_actions_api_list_generate_and_patch(client):
    """End-to-end through the endpoints: list (which regenerates), inspect, patch."""
    data = client.get("/api/actions").json()
    assert set(data) == {"count", "status_counts", "open_total", "actions"}
    assert {"open", "investigating", "resolved", "dismissed"} <= set(data["status_counts"])

    assert client.post("/api/actions/generate").json()["rules_run"] == 4

    # the shared fixture's neutral->frustrated MoodEvent trips the mood-swing rule
    actions = client.get("/api/actions").json()["actions"]
    assert any(a["rule_id"] == "negative_mood_shift" for a in actions)
    target = next(a for a in actions if a["rule_id"] == "negative_mood_shift")

    detail = client.get(f"/api/actions/{target['id']}").json()
    assert detail["entities"][0]["call_id"] == "testcall1"

    patched = client.patch(
        f"/api/actions/{target['id']}",
        json={"status": "investigating", "assigned_to": "  Dana  "},
    ).json()
    assert patched["status"] == "investigating"
    assert patched["assigned_to"] == "Dana"

    # a manual status survives the next regeneration
    assert client.post("/api/actions/generate").status_code == 200
    assert client.get(f"/api/actions/{target['id']}").json()["status"] == "investigating"

    assert client.patch(f"/api/actions/{target['id']}", json={"status": "bogus"}).status_code == 422
    assert client.get("/api/actions/999999").status_code == 404
    assert client.patch("/api/actions/999999", json={"status": "resolved"}).status_code == 404


def test_login_success_returns_token(client, real_auth):
    resp = client.post("/api/auth/login", json={"username": "manager", "password": _TEST_MANAGER_PW})
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str) and data["access_token"].count(".") == 2


def test_login_wrong_credentials_returns_401(client, real_auth):
    assert client.post("/api/auth/login", json={"username": "manager", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "ghost", "password": _TEST_MANAGER_PW}).status_code == 401


def test_protected_route_requires_token(client, real_auth):
    # no Authorization header -> 401
    assert client.get("/api/dashboard/overview").status_code == 401
    # garbage token -> 401
    assert client.get("/api/dashboard/overview", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_protected_route_accepts_valid_token(client, real_auth):
    token = client.post(
        "/api/auth/login", json={"username": "manager", "password": _TEST_MANAGER_PW}
    ).json()["access_token"]
    resp = client.get("/api/dashboard/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_health_and_login_stay_public(client, real_auth):
    assert client.get("/api/health").status_code == 200


def test_audio_route_accepts_token_query_param(client, real_auth):
    token = client.post(
        "/api/auth/login", json={"username": "manager", "password": _TEST_MANAGER_PW}
    ).json()["access_token"]
    # wrong/no token -> 401; valid token in the query string -> reaches the handler (404, file absent)
    assert client.get("/api/calls/testcall1/audio").status_code == 401
    assert client.get(f"/api/calls/testcall1/audio?token={token}").status_code == 404
