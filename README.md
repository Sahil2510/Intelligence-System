# Luvio Intelligence System

A voice-first AI assistant with a built-in web playground. Luvio transcribes speech, classifies intent, streams LLM responses, and can search the web, control Spotify playback, and remember context across conversations.

**Stack:** Python · FastAPI · Google Gemini · Langfuse · Redis · Mem0 · Spotify Web API

---

## Features

- **Voice & text chat** — speak or type; responses stream in real time
- **Intent routing** — automatically picks `normal`, `web_search`, or `spotify` per message
- **Web search** — Gemini + Google Search for live weather, news, scores, and more
- **Spotify control** — play, pause, skip, search, and queue tracks (OAuth login in the UI)
- **Memory**
  - **Short-term** — recent turns per chat via Redis
  - **Long-term** — semantic recall via Mem0 (optional)
- **Prompt management** — system prompts loaded from Langfuse with local caching
- **TTS** — browser Web Speech API (low latency) or server-side Gemini TTS (higher quality)

---

## Architecture

```
User (browser / mic)
        │
        ▼
┌───────────────────┐
│  FastAPI Playground│  app/playground.py
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Stream Pipeline   │  app/orchestrator/stream_pipeline.py
└─────────┬─────────┘
          │
    ┌─────┴─────┬─────────────┬──────────────┐
    ▼           ▼             ▼              ▼
 Transcribe   Classify     Prompt build    Tools
 (Gemini)     (Gemini)     (Langfuse)   web_search / spotify
    │           │             │              │
    └─────┬─────┴─────────────┴──────────────┘
          ▼
   Stream LLM response (Gemini)
          │
    ┌─────┴─────┐
    ▼           ▼
 Redis STM   Mem0 LTM
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.10+** | 3.11 or 3.12 recommended |
| **Docker** (optional) | For Redis via `docker compose` |
| **Google Gemini API key** | LLM, transcription, optional TTS |
| **Langfuse account** | Prompt templates (`system-prompt-luvio`, etc.) |
| **Spotify Developer app** | Optional; needed for music control |
| **Mem0 API key** | Optional; enables long-term memory |

---

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/Sahil2510/Intelligence-System.git
cd Intelligence-System
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### 4. Configure environment variables

```bash
# cp .env.example .env
```

Make `.env` and fill in at minimum:

- `GEMINI_API_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_PUBLIC_KEY`

See [Environment variables](#environment-variables) for the full list.

### 5. Start Redis (short-term memory)

```bash
docker compose up -d
```

Verify Redis is running:

```bash
docker compose ps
```

### 6. Run the playground

**Option A — CLI (recommended)**

```bash
python -m app.cli run
```

**Option B — helper script**

```bash
chmod +x luvio
./luvio run
```

**Option C — uvicorn directly**

```bash
uvicorn app.playground:app --host 127.0.0.1 --port 8000 --reload
```

### 7. Open the app

Visit **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

Allow microphone access when prompted for voice input.

---

## Spotify setup (optional)

1. Create an app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add redirect URI: `http://127.0.0.1:8000/api/spotify/callback`
3. Set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`.
4. Start the server and click **Connect Spotify** in the playground.
5. Have Spotify open on a device (desktop app, web player, or phone) for playback.

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `LANGFUSE_SECRET_KEY` | Yes | — | Langfuse secret key |
| `LANGFUSE_PUBLIC_KEY` | Yes | — | Langfuse public key |
| `LANGFUSE_BASE_URL` | No | `https://jp.cloud.langfuse.com` | Langfuse host |
| `LANGFUSE_PROMPT_LABEL` | No | `develop` | Prompt label to fetch |
| `SYSTEM_PROMPT_NAME` | No | `system-prompt-luvio` | Main system prompt name |
| `WEB_SEARCH_PROMPT_NAME` | No | `web-search-luvio` | Web search prompt name |
| `HOLDING_RESPONSE_PROMPT_NAME` | No | `holding-response-luvio` | Holding message prompt |
| `GEMINI_TTS_MODEL` | No | `gemini-2.5-flash-preview-tts` | Gemini TTS model |
| `GEMINI_TTS_VOICE` | No | `Kore` | Gemini TTS voice |
| `STREAM_TTS_MODE` | No | `browser` | `browser` or `gemini` |
| `SPOTIFY_CLIENT_ID` | No | — | Spotify app client ID |
| `SPOTIFY_CLIENT_SECRET` | No | — | Spotify app client secret |
| `SPOTIFY_REDIRECT_URI` | No | `http://127.0.0.1:8000/api/spotify/callback` | OAuth callback |
| `SPOTIFY_MARKET` | No | `IN` | Spotify market code |
| `REDIS_URL` | No | `redis://127.0.0.1:6379/0` | Redis connection URL |
| `REDIS_STM_MAX_MESSAGES` | No | `40` | Max messages stored per chat |
| `REDIS_STM_TTL_SECONDS` | No | `604800` | STM TTL (7 days) |
| `STM_HISTORY_TURN_LIMIT` | No | `5` | Turns included in prompt context |
| `MEM0_API_KEY` | No | — | Mem0 API key for long-term memory |
| `MEM0_SEARCH_LIMIT` | No | `5` | Max LTM results per query |
| `DEFAULT_USER_ID` | No | `playground-default` | Default user ID for memory |

Make `.env.example` as a starting point:

```bash
# cp .env.example .env
```

---

## CLI reference

```bash
# Start playground (default: 127.0.0.1:8000, auto-reload on)
python -m app.cli run

# Custom host / port
python -m app.cli run --host 0.0.0.0 --port 8080

# Disable auto-reload (production-like)
python -m app.cli run --no-reload
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web playground UI |
| `GET` | `/api/chats` | List chat sessions |
| `POST` | `/api/chats` | Create a new chat |
| `GET` | `/api/chats/{chat_id}` | Get chat by ID |
| `DELETE` | `/api/chats/{chat_id}` | Delete a chat |
| `POST` | `/api/query/stream` | Stream text query (NDJSON) |
| `POST` | `/api/voice-query/stream` | Stream voice query (audio upload) |
| `POST` | `/api/query` | Text query (non-streaming) |
| `POST` | `/api/voice-query` | Voice query (non-streaming) |
| `POST` | `/api/transcribe-audio` | Transcribe audio only |
| `POST` | `/api/tts` | Generate TTS audio |
| `GET` | `/api/tts/{job_id}` | Poll TTS job status |
| `POST` | `/api/classify-text` | Classify message intent |
| `GET` | `/api/memory/status` | Memory subsystem status |
| `GET` | `/api/spotify/status` | Spotify connection status |
| `GET` | `/api/spotify/login` | Start Spotify OAuth |
| `GET` | `/api/spotify/callback` | Spotify OAuth callback |
| `POST` | `/api/spotify/play` | Play a Spotify URI on a device |

Interactive API docs: **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

---

## Project structure

```
Intelligence-System/
├── app/
│   ├── cli.py                  # CLI entry point (`luvio run`)
│   ├── playground.py           # FastAPI app + web UI
│   ├── config.py               # Environment configuration
│   ├── orchestrator/
│   │   ├── intelligence.py     # Main orchestration logic
│   │   └── stream_pipeline.py  # Streaming response pipeline
│   ├── conversation/
│   │   ├── transcriber.py      # Audio → text (Gemini)
│   │   ├── responder.py        # LLM + TTS generation
│   │   └── sentence_buffer.py  # Sentence-level TTS buffering
│   ├── memory/
│   │   ├── short_term.py       # Redis STM
│   │   └── long_term.py        # Mem0 LTM
│   ├── context/
│   │   └── prompt_builder.py   # Assembles prompts with history/profile
│   ├── prompts/
│   │   └── prompt_registry.py  # Langfuse prompt fetching
│   ├── tools/
│   │   ├── tools.py            # Intent routing + tool execution
│   │   ├── tools.json          # Tool configuration
│   │   └── spotify_client.py   # Spotify API client
│   └── storage/
│       ├── chat_store.py       # Chat persistence (JSON files)
│       └── spotify_token_store.py
├── data/                       # Runtime data (gitignored)
├── docker-compose.yml          # Redis service
├── requirements.txt
├── pyproject.toml
├── luvio                         # Shell launcher
└── .env.example
```

---

## Batch evaluation (optional)

Run the orchestrator against sample audio files in `recordings/`:

```bash
python -m app.main
```

This reads queries from `dataset/queries_test.csv` and prints transcripts and responses.

---

## Development

```bash
# Activate venv
source venv/bin/activate

# Run with auto-reload
python -m app.cli run

# Test Langfuse connection
python tests/langfuse_connection.py

# Quick transcription + response smoke test
python tests/test_conversation.py
```

### Tool configuration

Enable or disable tools in `app/tools/tools.json`:

```json
{
  "tools": [
    { "name": "web_search", "enabled": true },
    { "name": "spotify", "enabled": true }
  ]
}
```

### TTS modes

| Mode | Env value | Behavior |
|------|-----------|----------|
| Browser (default) | `STREAM_TTS_MODE=browser` | Instant speech via Web Speech API |
| Gemini | `STREAM_TTS_MODE=gemini` | Server-generated audio, higher quality, more latency |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Redis connection refused` | Run `docker compose up -d` and confirm `REDIS_URL` |
| Langfuse prompt errors | Verify keys, prompt names, and label in Langfuse dashboard |
| Spotify won't play | Connect in UI; ensure Spotify is open on a target device |
| Microphone not working | Use HTTPS or `localhost`; grant browser mic permission |
| Import errors after clone | Run `pip install -r requirements.txt && pip install -e .` |

---

## Security notes

- **Never commit `.env`** — use `.env.example` as a template
- Rotate API keys if they were ever committed or shared
- `data/spotify/token.json` contains OAuth tokens and should stay local

---
