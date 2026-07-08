from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_notes.models.schemas import MeetingNote
from ai_notes.retrieval.answer_builder import build_meeting_answer
from ai_notes.retrieval.query_parser import QueryMode
from ai_notes.retrieval.retriever import MeetingRetriever
from ai_notes.storage.note_store import NoteStore
from ai_notes.storage.vector_index import VectorIndex


class AiNotesRetrievalTests(unittest.TestCase):

    def test_retriever_latest_meeting(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            notes_dir = root / "notes"
            notes_dir.mkdir()

            older = MeetingNote(
                user_id="user-1",
                title="Older Meeting",
                summary="Old summary",
                ended_at="2026-06-01T10:00:00",
            )
            newer = MeetingNote(
                user_id="user-1",
                title="Latest Meeting",
                summary="New summary",
                ended_at="2026-06-02T10:00:00",
            )

            store = NoteStore(notes_dir=notes_dir)
            store.save(older)
            store.save(newer)

            retriever = MeetingRetriever(
                note_store=store,
                vector_index=VectorIndex(index_path=root / "index.json"),
            )

            results = retriever.retrieve(
                user_id="user-1",
                query="latest meeting",
                mode=QueryMode.LATEST,
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Latest Meeting")

    @patch("ai_notes.retrieval.answer_builder.generate_response")
    def test_build_meeting_answer_without_notes(self, mock_generate):
        mock_generate.return_value = "I don't have a recorded meeting for that."

        answer = build_meeting_answer(
            "What happened in the latest meeting?",
            [],
            mode=QueryMode.LATEST,
        )

        self.assertIn("recorded meeting", answer.lower())
        mock_generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
