# Backend — Voxera

Quick start (backend folder):

1. Create and activate a virtual environment

```powershell
cd backend
python -m venv venv
venv\Scripts\activate
```

2. Install dependencies

```powershell
pip install -r requirements.txt
```

3. Required local data (place your dataset here):

- `data/vexora.db` — the SQLite database produced by the pipeline
- `data/audio/` — original MP3 files referenced by the DB
- `data/chroma_db/` — ChromaDB persistence directory (created after first sync)

4. Start the API server

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

5. Swagger / OpenAPI UI

Visit `http://127.0.0.1:8000/docs`

6. Run tests

```powershell
python -m pytest tests -v
```

7. Initial Chroma indexing (if local Chroma DB is empty)

```powershell
python -m app.services.chroma
```

Notes:
- The Chroma sync will index already-processed calls from `data/vexora.db` into the local `data/chroma_db` store. It does not re-run AssemblyAI transcription or Groq analysis; it only reads existing summaries and metadata and adds them to Chroma.
- Do NOT run tests against the real `data/vexora.db`. The test suite uses an in-memory test database.

Available API endpoints (17 total; `GET /api/health` and `POST /api/auth/login`
are public, the rest need `Authorization: Bearer <token>`):

- POST /api/auth/login — manager login, returns an 8-hour JWT
- GET  /api/health — liveness + live call count
- GET  /api/dashboard/overview — aggregated dashboard numbers
- GET  /api/calls/{call_id} — one processed call with transcript + evidence
- GET  /api/calls/{call_id}/audio — original MP3 (also accepts `?token=`)
- GET  /api/attention — needs-attention queue (`limit`, `offset`, `intent`, `final_mood`)
- GET  /api/intents — distinct intent values with counts
- GET  /api/customers — customers with aggregated stats
- GET  /api/customers/{customer_id}/calls — one customer's call history
- GET  /api/agents — agents with aggregated performance stats
- GET  /api/trends — top intents with unresolved counts + avg attention
- GET  /api/search?q= — structured + semantic search over calls
- POST /api/ask — "Ask Voxera" natural-language question over the data
- GET  /api/actions — Action Center task list (regenerates first; `status` filter)
- POST /api/actions/generate — force a regeneration pass
- GET  /api/actions/{action_id} — one action item + its entity cohort
- PATCH /api/actions/{action_id} — change status / assignee / note

Do not commit or share machine-specific absolute paths or API keys.
