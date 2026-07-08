from __future__ import annotations

from ai_notes.embeddings.embedder import NoteEmbedder
from ai_notes.models.schemas import MeetingNote
from ai_notes.retrieval.query_parser import QueryMode
from ai_notes.storage.note_store import NoteStore
from ai_notes.storage.vector_index import VectorIndex
from app.utils.pipeline_log import pipeline_complete, pipeline_start


class MeetingRetriever:

    def __init__(
        self,
        *,
        note_store: NoteStore | None = None,
        vector_index: VectorIndex | None = None,
        embedder: NoteEmbedder | None = None,
    ):
        self.note_store = note_store or NoteStore()
        self.vector_index = vector_index or VectorIndex()
        self.embedder = embedder or NoteEmbedder()

    def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        mode: QueryMode,
        limit: int = 3,
    ) -> list[MeetingNote]:
        pipeline_start(
            "ai-notes.retrieve",
            "Retrieving meeting notes",
            {"user_id": user_id, "mode": mode.value},
        )

        notes = self.note_store.list_notes(user_id=user_id)

        if not notes:
            pipeline_complete(
                "ai-notes.retrieve",
                "No meeting notes found",
                {"count": 0},
            )
            return []

        if mode == QueryMode.LATEST:
            result = notes[:1]
        elif mode in {QueryMode.PENDING_TASKS, QueryMode.COMPLETED_TASKS}:
            result = notes[:limit]
        else:
            query_vector = self.embedder.embed_query(query)
            ranked = self.vector_index.search(
                query_vector,
                user_id=user_id,
                limit=limit,
            )
            note_map = {note.id: note for note in notes}
            result = [
                note_map[note_id]
                for note_id, _score in ranked
                if note_id in note_map
            ]

            if not result:
                result = notes[:limit]

        pipeline_complete(
            "ai-notes.retrieve",
            "Meeting notes retrieved",
            {"count": len(result), "mode": mode.value},
        )
        return result
