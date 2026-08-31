# Voxera — Call-Centre Radar

Turns 1,441 recorded bank support calls into searchable, timestamped
transcripts and flags which calls need a manager's attention today, with
every judgment tied back to an exact moment in the call.

## Project layout

```
voxera/
├── backend/
│   ├── pipeline/          # audio -> transcript -> DB (this is the part documented below)
│   │   ├── step1_split_audio.py       # split stereo mp3 into agent/customer WAV
│   │   ├── step2_transcribe.py        # WAV -> timed text segments (AssemblyAI → Groq Whisper → local faster-whisper)
│   │   ├── step3_merge_transcript.py  # interleave both channels into one transcript
│   │   ├── metadata_utils.py          # parse the call metadata JSON
│   │   ├── process_one_call.py        # full pipeline for one call, saves to SQLite
│   │   └── batch_process.py           # runs process_one_call.py over all calls concurrently
│   ├── app/
│   │   ├── database/schema.py         # SQLite schema (SQLAlchemy models)
│   │   ├── auth.py                    # JWT manager auth — guards every route bar health + login
│   │   ├── services/analyze.py        # AI analysis (intent/mood/resolution/summary) — Groq chain, local Ollama fallback
│   │   ├── services/attention_score.py# deterministic needs-attention scoring
│   │   ├── services/chroma.py         # ChromaDB semantic search over call summaries
│   │   ├── services/ask.py            # "Ask Voxera" — LLM tool-calling loop over 4 read-only DB tools (POST /api/ask)
│   │   ├── services/actions.py        # Manager Action Center rule engine (GET/PATCH /api/actions)
│   │   └── main.py                    # FastAPI app — 17 routes, see "Running the API" below
│   ├── scripts/          # one-off migrations/backfills (add columns, intent_category, resolution evidence, audio paths)
│   └── tests/            # test_pipeline.py (deterministic pipeline) + test_api.py (API, stubbed auth)
├── data/
│   ├── audio/<id>.mp3       # provided
│   ├── metadata/<id>.json   # provided
│   ├── processed/           # WAVs produced by step 1 (gitignored)
│   ├── chroma_db/           # ChromaDB persistent store (gitignored)
│   └── vexora.db            # SQLite database (gitignored)
└── frontend/                 # React + Vite dashboard, see "Running the frontend" below
```

**Status:** the full pipeline (audio → transcript → AI analysis → scored,
queryable database) is complete and has processed all 1,441 calls. The
FastAPI layer (`backend/app/main.py`) and the React dashboard
(`frontend/`) are both built and run against that data. On top of the core
radar, three features are live: **JWT manager auth** (`app/auth.py`, login
page), the **Ask Voxera** assistant (`app/services/ask.py`, floating chat
widget), and the **Manager Action Center** (`app/services/actions.py`, a
tracked task list) — all covered below.

`app/services/analyze.py` calls Groq (`GROQ_MODEL_CHAIN` — currently
`openai/gpt-oss-120b` then `openai/gpt-oss-20b`) with a
JSON-schema-constrained prompt, falling back to a fully local Ollama model
(`llama3.1:8b`) as an always-succeeds last resort if Groq is unreachable.
Groq's JSON mode only guarantees valid JSON, not schema conformance, so the
response is validated against a Pydantic model and retried — with the
validation error fed back to the model — if it doesn't match. Every evidence
segment id it returns is checked against the real transcript before being
trusted; a hallucinated id is dropped to `None` rather than passed through,
per the brief's "wrong evidence scores negative" rule. If you swap models,
check `client.models.list()` against your account first — the SDK's type
hints can lag behind what's actually retired (`llama-3.3-70b-versatile`, the
originally planned default, was already gone from this account's catalog).

## Approach — how the work is done

The whole system is built around one rule: **every claim the UI makes must
point back to a specific line of a specific call.** That constraint drives
the pipeline, the data model, and the API.

**1. Ingest & transcribe (offline batch).** Each call is a stereo MP3 with
the agent on one channel and the customer on the other.
`step1_split_audio.py` splits the channels (bundled `ffmpeg`, no system
install). `step2_transcribe.py` transcribes each channel *separately* — so
speaker attribution is a fact of which file the audio came from, never a
diarization guess — through a three-layer fallback (AssemblyAI → Groq
Whisper → local `faster-whisper`) so a run never dies on a flaky provider.
`step3_merge_transcript.py` interleaves the two channels by timestamp into
one transcript and assigns each utterance a stable id (`seg_0`, `seg_1`, …).
Those ids are the citation anchors used everywhere downstream.

**2. AI analysis — bounded, validated, evidence-checked.**
`app/services/analyze.py` sends the numbered transcript to an LLM (Groq model
chain, local Ollama fallback) and asks for intent, mood arc, resolution
status, a summary, **and the `seg_*` id that justifies each judgment.** The
reply is validated against a Pydantic schema and retried with the error fed
back if it doesn't conform. Then every cited id is checked against the real
transcript — a hallucinated id is dropped to `None` rather than shown, on the
principle that wrong evidence is worse than no evidence.

**3. Needs-attention score — deterministic, not AI.**
`app/services/attention_score.py` computes the 0–100 priority score with
fixed rules (unresolved +30, ends angry +20, mood crash +15, repeat contact
+15, manager requested +10, long call +5). It mixes AI outputs (resolution,
mood) with pipeline-only facts (duration, prior-call count, a keyword scan
for escalation language). Each triggered rule is stored with its reason,
points, and the segment that justifies it — so the score is fully auditable
and reproducible, and a manager can see *why* a call surfaced.

**4. Serve (FastAPI, read-only over the populated DB).** The API never
re-transcribes or re-analyzes; it reads the SQLite DB the batch produced and
expands every stored `seg_*` reference into its text + timestamp so the
frontend can render evidence inline and deep-link the audio player. JWT auth
(`app/auth.py`) gates every route bar health/login.

**5. Two operator layers on top of the raw data.**
- **Ask Voxera** (`app/services/ask.py`): a natural-language question is
  answered by an LLM restricted to four parameterised, read-only tools
  (`aggregate`, `find_calls`, `semantic_search`, `get_call`) — no free-form
  SQL — and every call it cites is a real `call_id`.
- **Manager Action Center** (`app/services/actions.py`): deterministic rules
  turn standing problems (unresolved backlog, mood crashes, repeat
  unresolved contacts) into a tracked task list. Findings upsert by a stable
  `source_key` so manager status/notes survive regeneration; a rule that
  stops firing auto-resolves its task instead of deleting it.

**6. Dashboard (React/Vite).** A thin evidence-first client — shared
`EvidenceChip` / `ScorePill` / `MoodTimeline` / `AudioPlayer` primitives,
every score and quote clickable through to the exact moment in the call.

## Setup

1. **Python 3.10+** (developed against 3.13). Create and activate a venv:
   ```
   cd backend
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
   No system-wide ffmpeg install needed — `imageio-ffmpeg` bundles a static
   `ffmpeg.exe` that `step1_split_audio.py` calls directly.

   > Note: `requirements.txt` pins `chromadb>=1.0.0` and
   > `sentence-transformers>=3.2.0` rather than the older versions floated
   > early in planning — those older versions don't ship Python 3.13 wheels
   > and pip tries (and fails) to compile numpy from source.

2. **API keys** — copy `backend/.env.example` to `backend/.env` and fill in:
   ```
   ASSEMBLYAI_API_KEY=...
   GROQ_API_KEY=...
   ```
   Get a free AssemblyAI key at assemblyai.com (includes $50 free credit),
   and a free Groq key at console.groq.com.

   The same `.env` also holds the dashboard login (see `backend/app/auth.py`):
   ```
   JWT_SECRET_KEY=<long random string>
   MANAGER_USERNAME=manager
   MANAGER_PASSWORD_HASH='<bcrypt hash of the password>'
   ```
   Generate a hash with
   `python -c "import bcrypt; print(bcrypt.hashpw(b'your-pw', bcrypt.gensalt()).decode())"`.
   Every route except `/api/health` and `POST /api/auth/login` requires a
   bearer token from the login endpoint (8-hour expiry); the frontend shows a
   login page and stores the token in `localStorage`.

3. **Data** — place the provided files at `data/audio/*.mp3` and
   `data/metadata/*.json` (already done if you're reading this in the
   working copy).

## Running the pipeline

Initialize the database (creates `data/vexora.db`):
```
python backend/app/database/schema.py
```

Process one call end to end, to sanity-check your setup:
```
python backend/pipeline/process_one_call.py --audio data/audio/<id>.mp3 --metadata data/metadata/<id>.json
```

Process everything (this is the step that turns all 1,441 recordings into
transcripts and analysis, saved to SQLite):
```
python backend/pipeline/batch_process.py
```
- Runs 5 calls concurrently by default (`--concurrency N` to change).
- Skips calls already fully processed, so it's safe to stop and re-run.
- Errors for individual calls are logged to `data/errors.log`
  and don't stop the rest of the batch.
- `--limit 20` processes just the first 20 calls, useful for a quick test
  before committing to a full run (expect ~2-3 hours for all 1,441 at
  default concurrency, depending on your AssemblyAI rate limits).

Each pipeline stage can also be run and inspected on its own:
```
python backend/pipeline/step1_split_audio.py --audio data/audio/<id>.mp3
python backend/pipeline/step2_transcribe.py --wav data/processed/<id>_agent.wav --speaker agent
python backend/pipeline/step3_merge_transcript.py --demo
```

## Data model notes

The metadata JSON is nested, not flat — customer name lives at
`caller.metadata["first and last name"]`, agent name at
`agent.metadata.agent_name`, and `start_time_ms`/`end_time_ms` are Unix
epoch milliseconds. `metadata_utils.py` handles this.

`transcript_segments.segment_id` (e.g. `"seg_3"`) is the label shown in the
AI-facing transcript text and is what every evidence/citation field
(`intent_evidence_segment_id`, `mood_shift_segment_id`,
`attention_reasons.evidence_segment_id`) points at — always in the context
of a specific `call_id`.

The **needs-attention score is deterministic, not AI-generated** (see
`attention_score.py`): unresolved issue (+30), customer ends angry (+20),
major mood shift to negative (+15), repeat contact detected (+15), manager
requested (+10), call over 10 minutes (+5), capped at 100. It combines the
AI analysis output (resolution, mood) with pipeline-only facts (call
duration, prior-call history, a keyword scan for manager/supervisor/
escalate requests) — every triggered rule is stored with the reason, its
point value, and the transcript segment that justifies it where one exists.

## Running the API

Once the database is populated (see above — or use the `data/vexora.db` that
already ships with a full run of all 1,441 calls), start the FastAPI app
from `backend/`:
```
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
Interactive docs at `http://localhost:8000/docs`. CORS is pre-configured for
`http://localhost:3000` and `http://localhost:5173` (the frontend dev
server). All 17 routes: `/api/health` and `POST /api/auth/login` are open;
the rest require a bearer token (`/api/calls/{id}/audio` also accepts
`?token=`). `POST /api/auth/login`, `/api/health`,
`/api/dashboard/overview`, `/api/calls/{id}`, `/api/calls/{id}/audio`,
`/api/attention`, `/api/intents`, `/api/customers`,
`/api/customers/{id}/calls`, `/api/agents`, `/api/trends`, `/api/search?q=`,
`POST /api/ask`, `GET /api/actions`, `GET /api/actions/{id}`,
`PATCH /api/actions/{id}`, `POST /api/actions/generate`.

`GET /api/actions` powers the **Manager Action Center** — instead of another
analytics view, Voxera turns the data into a tracked task list. Deterministic
rules in `app/services/actions.py` (unresolved backlog by intent category,
severe negative mood swings, customers with repeat unresolved calls, calls that
ended with an upset customer) each emit findings with a stable `source_key`;
`generate()` upserts them into the `action_items` table so a manager's status
(`open` → `investigating` → `resolved` / `dismissed`), assignee, and notes
survive every regeneration. A task whose rule stops firing is auto-resolved,
not deleted — the problem lifecycle stays visible. The frozen `entity_ids`
cohort means "investigate these 33 calls" keeps meaning the same 33.
`GET /api/actions` regenerates before returning (best-effort); `PATCH` applies a
manager action; `POST /api/actions/generate` forces a pass. The `action_items`
table is created automatically on API startup for an existing `vexora.db`.

`POST /api/ask` is the "Ask Voxera" assistant — a natural-language question
(`{"question": "..."}`) answered by an LLM that can only call four read-only,
parameterised tools over the database (`app/services/ask.py`): aggregate,
find_calls, semantic_search, get_call. It plans the tool calls, reasons over
the real results, and returns `{answer, tool_calls, evidence_call_ids,
model_used}` — no arbitrary SQL, and every cited call is a real `call_id`.
Needs `GROQ_API_KEY`; returns 503 if the provider is unreachable.

## Running the frontend

Requires the API running on `:8000` (above) — the dashboard reads
everything through it, nothing is re-transcribed or re-analyzed client-side.
```
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`. First load shows the login page
(`src/pages/Login.jsx`); sign in with the manager credentials from
`backend/.env` and the token is kept in `localStorage` (key `voxera-token`),
attached to every request by an axios interceptor that bounces you back to
`/login` on any 401 (`src/api/client.js`, `src/context/AuthContext.jsx`).
`frontend/.env` points it at `VITE_API_BASE_URL=http://localhost:8000` —
change that if you run the API elsewhere. Stack: React + Vite, Tailwind CSS
v4, React Router, Recharts, Axios, lucide-react. Dark/light theme toggle
persists in `localStorage` (defaults to dark). See
`frontend/src/components/` for the shared, evidence-first building blocks
(`EvidenceChip`, `ScorePill`, `MoodChip`, `MoodTimeline`, `AudioPlayer`)
reused across the pages.

**Ask Voxa** (`src/components/AskWidget.jsx`) is a floating chat widget
pinned to the bottom-left corner on every page, over `POST /api/ask`: ask a
question in plain English, get an answer with the supporting `call_id`s
rendered as chips that link straight to the call detail, plus a trace of
which tools the assistant ran. Open/closed state persists in `localStorage`.
The launcher/avatar is the Voxa mascot in `public/voxa.svg` (the source
artwork with its `viewBox` cropped to the circular badge; falls back to an
icon if it fails to load).

**Action Center** (`src/pages/ActionCenter.jsx`, sidebar → Action Center) is
the operations counterpart to the Attention Queue: it lists the tasks
`GET /api/actions` generated, grouped by Active / Resolved / Dismissed, each
with a priority dot, the affected calls/customers (expand to drill in), and
the manager controls — Investigating, Resolved, Assign follow-up, Dismiss,
Reopen. Status changes `PATCH` straight back and the list refreshes.

## Testing

`tests/test_pipeline.py` covers the deterministic parts of the pipeline
(transcript merging, timestamp formatting, needs-attention scoring) — no API
keys, network calls, or database needed. `tests/test_api.py` exercises the
FastAPI routes against an in-memory SQLite DB with auth stubbed (plus a
`real_auth` fixture that drives the genuine JWT path). Both run in well under
a second:
```
cd backend
python -m pytest tests/ -v
```

## Known Tradeoffs

Customer identity is matched by name only (the dataset contains no customer
ID field). Two customers with identical names will be merged into one
history. This is a known tradeoff given the dataset structure, not a bug.

In this dataset it's not a rare edge case: all 1,441 calls resolve to only
100 unique customer names, a ~14.4x average reuse rate. So most "customer
histories" in the app are really an aggregate of several different real
people who happen to share a name, not one person's repeat contacts.

## Known gaps

- `GET /api/calls/{id}` doesn't return `resolution_evidence_segment_id` or
  `intent_category` yet, even though both columns exist in the DB (backfilled
  by `backend/scripts/`). The frontend's Resolution card is built to show
  these once the API adds them — until then it renders an explicit
  "Evidence pending" state rather than hiding the slot.
- `GET /api/trends` and the Attention Queue's intent badges group on the raw
  free-text `Call.intent` column, not the closed `intent_category` enum —
  same reason, and same forward-compatible styling on the frontend.
