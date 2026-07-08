from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ai_notes.ingestion.session_manager import SessionManager
from ai_notes.pipeline.ingest_stream import IngestPipeline
from ai_notes.storage.note_store import NoteStore
from app.config import DEFAULT_USER_ID
from app.conversation.responder import generate_speech
from app.orchestrator.stream_pipeline import stream_ndjson_response

router = APIRouter(prefix="/api/ai-notes", tags=["ai-notes"])

_session_manager = SessionManager()
_ingest_pipeline = IngestPipeline(session_manager=_session_manager)
_note_store = NoteStore()


def _resolve_user_id(user_id: str | None) -> str:
    return (user_id or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID


@router.post("/session/start")
def start_session(user_id: str | None = Form(default=None)):
    resolved_user_id = _resolve_user_id(user_id)
    session = _session_manager.start_session(resolved_user_id)

    try:
        speech = generate_speech("Meeting recording started.")
        tts = {
            "audio_base64": speech["audio_base64"],
            "mime_type": speech["mime_type"],
        }
    except Exception:
        tts = None

    return {
        "session_id": session.session_id,
        "user_id": resolved_user_id,
        "status": session.status,
        "started_at": session.started_at,
        "message": "Meeting recording started.",
        "tts": tts,
    }


@router.get("/sessions/active")
def get_active_session(user_id: str | None = None):
    resolved_user_id = _resolve_user_id(user_id)
    session = _session_manager.get_active_session(resolved_user_id)

    if session is None:
        return {"active": False, "user_id": resolved_user_id}

    return {
        "active": True,
        "user_id": resolved_user_id,
        "session_id": session.session_id,
        "status": session.status,
        "started_at": session.started_at,
        "chunk_count": len(session.chunks),
    }


@router.post("/session/chunk")
async def upload_chunk(
    audio: UploadFile = File(...),
    user_id: str | None = Form(default=None),
):
    resolved_user_id = _resolve_user_id(user_id)
    audio_bytes = await audio.read()

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio chunk")

    try:
        session = _session_manager.append_chunk(
            resolved_user_id,
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "audio/webm",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "session_id": session.session_id,
        "chunk_count": len(session.chunks),
        "status": session.status,
    }


@router.post("/session/end")
def end_session(user_id: str | None = Form(default=None)):
    resolved_user_id = _resolve_user_id(user_id)

    return StreamingResponse(
        stream_ndjson_response(
            _ingest_pipeline.stream_end_session(resolved_user_id)
        ),
        media_type="application/x-ndjson",
    )


@router.get("/notes")
def list_notes(user_id: str | None = None):
    resolved_user_id = _resolve_user_id(user_id)
    notes = _note_store.list_notes(user_id=resolved_user_id)

    return {
        "notes": [
            {
                "id": note.id,
                "title": note.title,
                "summary": note.summary,
                "keywords": note.keywords,
                "pending_tasks": note.pending_tasks,
                "completed_tasks": note.completed_tasks,
                "started_at": note.started_at,
                "ended_at": note.ended_at,
                "created_at": note.created_at,
            }
            for note in notes
        ]
    }
