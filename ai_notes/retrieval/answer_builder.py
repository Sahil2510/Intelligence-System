from __future__ import annotations

from ai_notes.models.schemas import MeetingNote
from ai_notes.prompts.meeting_notes import retrieval_prompt
from ai_notes.retrieval.query_parser import QueryMode
from app.conversation.responder import generate_response, stream_response


def _format_note_context(notes: list[MeetingNote], mode: QueryMode) -> str:
    if not notes:
        return "No meeting notes available."

    blocks: list[str] = []

    for note in notes:
        lines = [
            f"Title: {note.title}",
            f"Date: {note.ended_at or note.created_at}",
            f"Summary: {note.summary}",
            f"Keywords: {', '.join(note.keywords)}",
        ]

        if mode == QueryMode.PENDING_TASKS or note.pending_tasks:
            lines.append(f"Pending tasks: {', '.join(note.pending_tasks) or 'None'}")

        if mode == QueryMode.COMPLETED_TASKS or note.completed_tasks:
            lines.append(
                f"Completed tasks: {', '.join(note.completed_tasks) or 'None'}"
            )

        if note.actionable_items:
            action_lines = [
                f"- {item.task} ({item.status.value})"
                for item in note.actionable_items
            ]
            lines.append("Action items:\n" + "\n".join(action_lines))

        blocks.append("\n".join(lines))

    return "\n\n---\n\n".join(blocks)


def build_meeting_answer(
    question: str,
    notes: list[MeetingNote],
    *,
    mode: QueryMode,
) -> str:
    context = _format_note_context(notes, mode)
    prompt = retrieval_prompt(question, context)
    return generate_response(prompt)


def stream_meeting_answer(
    question: str,
    notes: list[MeetingNote],
    *,
    mode: QueryMode,
):
    context = _format_note_context(notes, mode)
    prompt = retrieval_prompt(question, context)
    yield from stream_response(prompt)
