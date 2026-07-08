# AI Notes — Voice-Only Meeting Notes

Meeting-focused subsystem for Luvio: live voice capture, structured extraction, embedding search, and spoken retrieval via the main chat pipeline.

## Progress

- [x] Phase 1 — Scaffold, schemas, config, prompts
- [x] Phase 2 — Live session ingestion (Redis + chunk API + ingest stream)
- [x] Phase 3 — Summarizer, embedder, note store, vector index
- [x] Phase 4 — `meeting_notes` intent + retrieval handler
- [x] Phase 5 — Playground Meeting Mode UI + tests

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ai-notes/session/start` | Begin live meeting session |
| POST | `/api/ai-notes/session/chunk` | Upload audio segment during meeting |
| POST | `/api/ai-notes/session/end` | End session, stream processing (NDJSON) |
| GET | `/api/ai-notes/sessions/active` | Active session for user |
| GET | `/api/ai-notes/notes` | List saved meeting notes |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEETING_NOTES_EXTRACT_PROMPT_NAME` | `meeting-notes-extract-luvio` | Langfuse extraction prompt |
| `MEETING_NOTES_RETRIEVAL_PROMPT_NAME` | `meeting-notes-retrieval-luvio` | Langfuse retrieval prompt |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model |
| `GEMINI_EMBEDDING_DIMENSION` | `768` | Output vector size |
| `AI_NOTES_SESSION_TTL_SECONDS` | `86400` | Redis session TTL (24h) |
| `AI_NOTES_CHUNK_INTERVAL_SECONDS` | `30` | Suggested auto-chunk interval in UI |

## Data Location

- Notes: `data/notes/{note_id}.json`
- Vector index: `data/notes/index.json`
- Session chunks: `data/notes/sessions/{session_id}/chunks/`

## Voice Flow

1. **Ingestion** — Start Meeting Mode → audio chunks uploaded every ~30s → End Meeting → structured note saved with embeddings.
2. **Retrieval** — Ask in normal Luvio chat: *"What happened in the latest meeting?"* → `meeting_notes` intent → spoken answer.
