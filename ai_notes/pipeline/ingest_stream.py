from __future__ import annotations

from typing import Any, Iterator

from ai_notes.embeddings.embedder import NoteEmbedder
from ai_notes.ingestion.chunk_processor import ChunkProcessor
from ai_notes.ingestion.session_manager import SessionManager
from ai_notes.ingestion.summarizer import MeetingSummarizer
from ai_notes.models.schemas import MeetingNote, NoteEmbeddings
from ai_notes.storage.note_store import NoteStore
from ai_notes.storage.vector_index import VectorIndex
from app.utils.pipeline_log import pipeline_complete, pipeline_error, pipeline_start


class IngestPipeline:

    def __init__(
        self,
        *,
        session_manager: SessionManager | None = None,
        chunk_processor: ChunkProcessor | None = None,
        summarizer: MeetingSummarizer | None = None,
        embedder: NoteEmbedder | None = None,
        note_store: NoteStore | None = None,
        vector_index: VectorIndex | None = None,
    ):
        self.session_manager = session_manager or SessionManager()
        self.chunk_processor = chunk_processor or ChunkProcessor()
        self.summarizer = summarizer or MeetingSummarizer()
        self.embedder = embedder or NoteEmbedder()
        self.note_store = note_store or NoteStore()
        self.vector_index = vector_index or VectorIndex()

    def stream_end_session(self, user_id: str) -> Iterator[dict[str, Any]]:
        pipeline_start(
            "ai-notes.session.end",
            "Ending meeting notes session",
            {"user_id": user_id},
        )

        session = self.session_manager.get_active_session(user_id)

        if session is None:
            yield {
                "type": "error",
                "message": "No active meeting session to end.",
            }
            return

        if not session.chunks:
            self.session_manager.fail_session(user_id)
            yield {
                "type": "error",
                "message": "Meeting session has no recorded audio chunks.",
            }
            return

        session = self.session_manager.mark_processing(user_id)
        yield {
            "type": "status",
            "message": "Transcribing meeting audio...",
            "session_id": session.session_id,
        }

        try:
            transcript, segments = self.chunk_processor.transcribe_session(session)

            if not transcript.strip():
                raise ValueError("Could not transcribe any meeting audio.")

            yield {
                "type": "status",
                "message": "Extracting structured meeting notes...",
            }

            extraction = self.summarizer.extract(transcript)

            yield {
                "type": "status",
                "message": "Generating embeddings...",
            }

            title_vector = self.embedder.embed_title(extraction.title)
            summary_vector = self.embedder.embed_summary(
                extraction.summary,
                extraction.keywords,
            )

            note = MeetingNote(
                user_id=user_id,
                title=extraction.title,
                summary=extraction.summary,
                keywords=extraction.keywords,
                actionable_items=extraction.actionable_items,
                pending_tasks=extraction.pending_tasks,
                completed_tasks=extraction.completed_tasks,
                raw_transcript=transcript,
                segments=segments,
                embeddings=NoteEmbeddings(
                    title=title_vector,
                    summary=summary_vector,
                ),
                started_at=session.started_at,
                ended_at=session.ended_at,
            )

            self.note_store.save(note)
            self.vector_index.upsert(
                note.id,
                title_vector=title_vector,
                summary_vector=summary_vector,
                user_id=user_id,
                created_at=note.created_at,
            )
            self.session_manager.complete_session(user_id, note.id)

            spoken = (
                f"Meeting notes saved as {note.title}. "
                f"I captured {len(note.pending_tasks)} pending tasks."
            )

            pipeline_complete(
                "ai-notes.session.end",
                "Meeting notes session completed",
                {"note_id": note.id, "title": note.title},
            )

            yield {
                "type": "note_saved",
                "note_id": note.id,
                "title": note.title,
                "summary": note.summary,
                "pending_tasks": note.pending_tasks,
                "completed_tasks": note.completed_tasks,
            }

            yield {
                "type": "token",
                "text": spoken,
            }

            yield {
                "type": "done",
                "response": spoken,
                "note_id": note.id,
                "title": note.title,
            }
        except Exception as exc:
            self.session_manager.fail_session(user_id)
            pipeline_error(
                "ai-notes.session.end",
                "Failed to process meeting session",
                {"error": str(exc)},
            )
            yield {
                "type": "error",
                "message": str(exc),
            }
