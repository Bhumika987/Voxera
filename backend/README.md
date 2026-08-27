# Backend — Vexora

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

Available API endpoints:

- GET /api/health
- GET /api/dashboard/overview
- GET /api/attention
- GET /api/calls/{call_id}
- GET /api/calls/{call_id}/audio
- GET /api/customers
- GET /api/customers/{customer_id}/calls
- GET /api/agents
- GET /api/trends
- GET /api/search?q=

Do not commit or share machine-specific absolute paths or API keys.
