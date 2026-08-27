import sys
import types
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db
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
    """Override FastAPI DB dependency to use the shared in-memory SessionLocal."""

    def _get_test_db():
        db = test_db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.clear()


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
