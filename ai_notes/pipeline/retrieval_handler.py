from __future__ import annotations

from ai_notes.retrieval.answer_builder import stream_meeting_answer
from ai_notes.retrieval.query_parser import parse_meeting_query
from ai_notes.retrieval.retriever import MeetingRetriever
from app.utils.pipeline_log import pipeline_complete, pipeline_start


def stream_meeting_notes_response(
    transcript: str,
    *,
    user_id: str,
):
    pipeline_start(
        "ai-notes.retrieval",
        "Handling meeting notes retrieval query",
        {"user_id": user_id},
    )

    mode, normalized_query = parse_meeting_query(transcript)
    retriever = MeetingRetriever()
    notes = retriever.retrieve(
        user_id=user_id,
        query=normalized_query,
        mode=mode,
    )

    if not notes:
        message = "I don't have a recorded meeting for that."
        yield message
        pipeline_complete(
            "ai-notes.retrieval",
            "Meeting notes retrieval completed with no results",
            {"mode": mode.value},
        )
        return

    yield from stream_meeting_answer(
        transcript,
        notes,
        mode=mode,
    )

    pipeline_complete(
        "ai-notes.retrieval",
        "Meeting notes retrieval completed",
        {"mode": mode.value, "note_count": len(notes)},
    )
