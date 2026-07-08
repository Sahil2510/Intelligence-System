import unittest

from ai_notes.models.schemas import (
    ActionableItem,
    ExtractionResult,
    MeetingNote,
    TaskStatus,
)
from ai_notes.retrieval.query_parser import QueryMode, parse_meeting_query


class AiNotesSchemaTests(unittest.TestCase):

    def test_extraction_result_defaults(self):
        result = ExtractionResult(
            title="Weekly Sync",
            summary="Discussed roadmap.",
        )
        self.assertEqual(result.title, "Weekly Sync")
        self.assertEqual(result.keywords, [])
        self.assertEqual(result.pending_tasks, [])

    def test_meeting_note_round_trip(self):
        note = MeetingNote(
            user_id="test-user",
            title="Planning",
            summary="Aligned on milestones.",
            keywords=["roadmap"],
            actionable_items=[
                ActionableItem(task="Send doc", status=TaskStatus.PENDING),
            ],
            pending_tasks=["Send doc"],
            completed_tasks=["Agree scope"],
        )
        restored = MeetingNote.from_storage_dict(note.to_storage_dict())
        self.assertEqual(restored.id, note.id)
        self.assertEqual(restored.pending_tasks, ["Send doc"])

    def test_parse_latest_meeting_query(self):
        mode, _query = parse_meeting_query("What happened in the latest meeting?")
        self.assertEqual(mode, QueryMode.LATEST)

    def test_parse_pending_tasks_query(self):
        mode, _query = parse_meeting_query(
            "What are my pending tasks from meetings?"
        )
        self.assertEqual(mode, QueryMode.PENDING_TASKS)

    def test_parse_semantic_query(self):
        mode, _query = parse_meeting_query("What did we decide about pricing?")
        self.assertEqual(mode, QueryMode.SEMANTIC)


if __name__ == "__main__":
    unittest.main()
