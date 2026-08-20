# Vexora — Call-Centre Radar

Turns 1,441 recorded bank support calls into searchable, timestamped
transcripts and flags which calls need a manager's attention today, with
every judgment tied back to an exact moment in the call.

## Project layout

```
vexora/
├── backend/
│   ├── pipeline/          # audio -> transcript -> DB (this is the part documented below)
│   │   ├── step1_split_audio.py       # split stereo mp3 into agent/customer WAV
│   │   ├── step2_transcribe.py        # AssemblyAI: WAV -> timed text segments
│   │   ├── step3_merge_transcript.py  # interleave both channels into one transcript
│   │   ├── metadata_utils.py          # parse the call metadata JSON
│   │   ├── process_one_call.py        # full pipeline for one call, saves to SQLite
│   │   └── batch_process.py           # runs process_one_call.py over all calls concurrently
│   └── app/
│       ├── database/schema.py         # SQLite schema (SQLAlchemy models)
│       ├── services/analyze.py        # AI analysis (intent/mood/resolution/summary) — Groq (openai/gpt-oss-120b)
│       ├── services/attention_score.py# deterministic needs-attention scoring
│       └── api/                       # FastAPI routes — not yet built
├── data/
│   ├── audio/<id>.mp3       # provided
│   ├── metadata/<id>.json   # provided
│   ├── processed/           # WAVs produced by step 1 (gitignored)
│   └── vexora.db            # SQLite database (gitignored)
└── frontend/                 # dashboard — not yet built
```

**Status:** the full pipeline (audio → transcript → AI analysis → scored,
queryable database) is complete, tested end-to-end against real audio, real
AssemblyAI transcription, and real Groq analysis. The FastAPI layer and the
React dashboard are not built yet.

`app/services/analyze.py` calls Groq's `openai/gpt-oss-120b` model with a
JSON-schema-constrained prompt (Groq's JSON mode only guarantees valid JSON,
not schema conformance, so the response is validated against a Pydantic
model and retried — with the validation error fed back to the model — if it
doesn't match). Every evidence segment id it returns is checked against the
real transcript before being trusted; a hallucinated id is dropped to `None`
rather than passed through, per the brief's "wrong evidence scores negative"
rule. If you swap models, check `client.models.list()` against your account
first — the SDK's type hints can lag behind what's actually retired
(`llama-3.3-70b-versatile`, the originally planned default, was already gone
from this account's catalog).

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

## Testing

Unit tests cover the deterministic parts of the pipeline (transcript merging,
timestamp formatting, needs-attention scoring) — no API keys, network calls,
or database needed, so they run in well under a second:
```
cd backend
python -m pytest tests/ -v
```

## Known Tradeoffs

Customer identity is matched by name only (the dataset contains no customer
ID field). Two customers with identical names will be merged into one
history. This is a known tradeoff given the dataset structure, not a bug.

## Next steps (not yet built)

- `backend/app/api/` — FastAPI routes exposing the per-call analysis via the
  contract in the project brief.
- `frontend/` — the React dashboard.
