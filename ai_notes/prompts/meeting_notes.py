from functools import lru_cache

from app.config import (
    MEETING_NOTES_EXTRACT_PROMPT_NAME,
    MEETING_NOTES_RETRIEVAL_PROMPT_NAME,
)
from app.prompts.prompt_registry import PromptRegistry

EXTRACTION_FALLBACK = """You extract structured meeting notes from a transcript.

Return JSON only with these fields:
- title: short meeting title (infer if not stated)
- summary: concise summary under 150 words for voice playback
- keywords: 5-10 topic keywords
- actionable_items: array of {task, owner, due_date, status} where status is "pending" or "completed"
- pending_tasks: list of open task strings
- completed_tasks: list of done task strings

Rules:
- Split tasks into pending vs completed based on language cues.
- Infer owners and due dates only when clearly stated.
- Do not invent facts not present in the transcript.

Transcript:
{transcript}
"""

RETRIEVAL_FALLBACK = """You answer questions about past meetings using the provided note context.

Rules:
- Reply in 2-4 short spoken sentences (no markdown, bullets, or lists).
- If asked about the latest meeting, lead with title and date.
- Include key decisions and outstanding tasks when relevant.
- If no matching meeting exists, say: "I don't have a recorded meeting for that."

User question:
{question}

Meeting notes context:
{context}
"""


@lru_cache
def _registry() -> PromptRegistry:
    return PromptRegistry()


def extraction_prompt(transcript: str) -> str:
    try:
        template = _registry().get_text_prompt(MEETING_NOTES_EXTRACT_PROMPT_NAME)
        return template.replace("{transcript}", transcript)
    except Exception:
        return EXTRACTION_FALLBACK.format(transcript=transcript)


def retrieval_prompt(question: str, context: str) -> str:
    try:
        template = _registry().get_text_prompt(MEETING_NOTES_RETRIEVAL_PROMPT_NAME)
        return (
            template.replace("{question}", question).replace("{context}", context)
        )
    except Exception:
        return RETRIEVAL_FALLBACK.format(question=question, context=context)
