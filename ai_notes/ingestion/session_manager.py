from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import redis

from ai_notes.models.schemas import MeetingSession, SessionChunkRef
from app.config import AI_NOTES_SESSION_TTL_SECONDS, REDIS_URL
from app.utils.pipeline_log import pipeline_complete, pipeline_error, pipeline_start

SESSIONS_DIR = Path("data/notes/sessions")


class SessionManager:

    KEY_PREFIX = "ai-notes:session"

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        sessions_dir: Path = SESSIONS_DIR,
        ttl_seconds: int = AI_NOTES_SESSION_TTL_SECONDS,
    ):
        self.redis_url = redis_url
        self.sessions_dir = sessions_dir
        self.ttl_seconds = ttl_seconds
        self._client: redis.Redis | None = None

    def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._client

    def _key(self, user_id: str) -> str:
        return f"{self.KEY_PREFIX}:{user_id}"

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def _chunks_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "chunks"

    def _load_session(self, user_id: str) -> MeetingSession | None:
        raw = self._get_client().get(self._key(user_id))

        if not raw:
            return None

        return MeetingSession.model_validate(json.loads(raw))

    def _save_session(self, session: MeetingSession) -> None:
        client = self._get_client()
        client.set(
            self._key(session.user_id),
            session.model_dump_json(),
            ex=self.ttl_seconds if self.ttl_seconds > 0 else None,
        )

    def get_active_session(self, user_id: str) -> MeetingSession | None:
        session = self._load_session(user_id)

        if session is None or session.status != "active":
            return None

        return session

    def start_session(self, user_id: str) -> MeetingSession:
        pipeline_start(
            "ai-notes.session.start",
            "Starting meeting notes session",
            {"user_id": user_id},
        )

        existing = self.get_active_session(user_id)

        if existing:
            pipeline_complete(
                "ai-notes.session.start",
                "Existing active session returned",
                {"session_id": existing.session_id},
            )
            return existing

        session = MeetingSession(user_id=user_id)
        self._chunks_dir(session.session_id).mkdir(parents=True, exist_ok=True)
        self._save_session(session)

        pipeline_complete(
            "ai-notes.session.start",
            "Meeting notes session started",
            {"session_id": session.session_id},
        )
        return session

    def append_chunk(
        self,
        user_id: str,
        *,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
    ) -> MeetingSession:
        session = self.get_active_session(user_id)

        if session is None:
            raise ValueError("No active meeting session for this user")

        chunk_index = len(session.chunks)
        chunk_path = self._chunks_dir(session.session_id) / f"{chunk_index}.webm"
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_path.write_bytes(audio_bytes)

        session.chunks.append(
            SessionChunkRef(
                index=chunk_index,
                path=str(chunk_path),
                mime_type=mime_type,
                recorded_at=datetime.utcnow().isoformat(),
            )
        )
        self._save_session(session)
        return session

    def mark_processing(self, user_id: str) -> MeetingSession:
        session = self._load_session(user_id)

        if session is None:
            raise ValueError("No meeting session for this user")

        session.status = "processing"
        session.ended_at = datetime.utcnow().isoformat()
        self._save_session(session)
        return session

    def update_session(self, session: MeetingSession) -> None:
        self._save_session(session)

    def complete_session(self, user_id: str, note_id: str) -> None:
        session = self._load_session(user_id)

        if session is None:
            return

        session.status = "completed"
        session.note_id = note_id
        self._save_session(session)
        self.cleanup_session_files(session.session_id)
        self._get_client().delete(self._key(user_id))

    def cleanup_session_files(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)

        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

    def fail_session(self, user_id: str) -> None:
        session = self._load_session(user_id)

        if session is None:
            return

        self.cleanup_session_files(session.session_id)
        self._get_client().delete(self._key(user_id))

        pipeline_error(
            "ai-notes.session.end",
            "Meeting session failed and was cleaned up",
            {"user_id": user_id},
        )
