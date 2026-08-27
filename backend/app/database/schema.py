"""
SQLite schema for Vexora, via SQLAlchemy ORM.

Design notes:
- `calls.id` is the call's own id from the source data (the mp3/json filename
  stem, e.g. "004860b1ab2e4c88") rather than a synthetic integer — it's
  already a unique key and it's what audio_path / transcript files are
  named after, so reusing it avoids a pointless lookup table.
- `transcript_segments.segment_id` (e.g. "seg_3") is the call-scoped label
  produced by step3_merge_transcript.py — the same label that appears in
  the formatted transcript text the AI reads and cites evidence from.
  Every "evidence_segment_id" / "mood_shift_segment_id" column elsewhere
  stores this string label (always in the context of a known call_id),
  NOT the internal surrogate `id`.
- `calls.processed` lets batch_process.py skip calls that already made it
  all the way through the pipeline, so re-running the batch is safe.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "vexora.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """WAL mode + a busy timeout so batch_process.py's concurrent workers don't
    hit 'database is locked' errors when multiple calls commit around the same time."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    calls: Mapped[list["Call"]] = relationship(back_populates="customer")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    calls: Mapped[list["Call"]] = relationship(back_populates="agent")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # source call id / filename stem
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    audio_path: Mapped[str] = mapped_column(String(512), nullable=False)  # path to the original stereo mp3

    # --- AI analysis output (filled in by app/services/analyze.py) ---
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_evidence_segment_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent_category: Mapped[str | None] = mapped_column(String(32), nullable=True)  # closed vocabulary, see analyze.py's INTENT_CATEGORIES

    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "resolved" | "unresolved" | "unknown"
    resolution_evidence_segment_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # <= 40 words

    initial_mood: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_mood: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mood_shift_time: Mapped[float | None] = mapped_column(Float, nullable=True)  # seconds into the call
    mood_shift_segment_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- deterministic score (app/services/attention_score.py), not AI-generated ---
    attention_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which model actually produced the analysis (e.g. "openai/gpt-oss-120b",
    # "openai/gpt-oss-20b", "llama3.1:8b (ollama)") — lets you find and redo
    # calls that fell back to a lower-tier model with a plain SQL query
    # instead of reconstructing it from terminal logs by hand.
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Which transcription provider handled each channel, e.g.
    # "agent=assemblyai,customer=assemblyai" — a value other than both-assemblyai
    # means step2_transcribe.py's fallback chain kicked in for that channel.
    transcription_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)

    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    customer: Mapped["Customer"] = relationship(back_populates="calls")
    agent: Mapped["Agent"] = relationship(back_populates="calls")
    segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    attention_reasons: Mapped[list["AttentionReason"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    mood_events: Mapped[list["MoodEvent"]] = relationship(back_populates="call", cascade="all, delete-orphan")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), nullable=False, index=True)
    segment_id: Mapped[str] = mapped_column(String(32), nullable=False)  # "seg_1", "seg_2", ... (scoped to this call)
    speaker: Mapped[str] = mapped_column(String(16), nullable=False)  # "agent" | "customer"
    start_time: Mapped[float] = mapped_column(Float, nullable=False)  # seconds
    end_time: Mapped[float] = mapped_column(Float, nullable=False)  # seconds
    text: Mapped[str] = mapped_column(Text, nullable=False)

    call: Mapped["Call"] = relationship(back_populates="segments")


class AttentionReason(Base):
    """One triggered rule behind a call's attention_score (see attention_score.py)."""

    __tablename__ = "attention_reasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "Unresolved issue"
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_segment_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    call: Mapped["Call"] = relationship(back_populates="attention_reasons")


class MoodEvent(Base):
    """A detected mood transition within a call (there can be more than one)."""

    __tablename__ = "mood_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), nullable=False, index=True)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)  # seconds into the call
    mood_before: Mapped[str] = mapped_column(String(32), nullable=False)
    mood_after: Mapped[str] = mapped_column(String(32), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(32), nullable=False)

    call: Mapped["Call"] = relationship(back_populates="mood_events")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
