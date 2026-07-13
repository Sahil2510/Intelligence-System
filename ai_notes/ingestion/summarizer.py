from __future__ import annotations

import json

from google import genai
from google.genai import types

from ai_notes.models.schemas import ActionableItem, ExtractionResult, TaskStatus
from ai_notes.prompts.meeting_notes import extraction_prompt
from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.utils.pipeline_log import pipeline_complete, pipeline_start

MODEL = GEMINI_MODEL
_client = genai.Client(api_key=GEMINI_API_KEY)

EXTRACTION_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "title": types.Schema(type=types.Type.STRING),
        "summary": types.Schema(type=types.Type.STRING),
        "keywords": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
        "actionable_items": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "task": types.Schema(type=types.Type.STRING),
                    "owner": types.Schema(type=types.Type.STRING),
                    "due_date": types.Schema(type=types.Type.STRING),
                    "status": types.Schema(type=types.Type.STRING),
                },
                required=["task"],
            ),
        ),
        "pending_tasks": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
        "completed_tasks": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
    },
    required=[
        "title",
        "summary",
        "keywords",
        "actionable_items",
        "pending_tasks",
        "completed_tasks",
    ],
)


class MeetingSummarizer:

    MAX_CHARS = 120_000
    CHUNK_CHARS = 6000

    def extract(self, transcript: str) -> ExtractionResult:
        pipeline_start(
            "ai-notes.summarize",
            "Extracting structured meeting notes",
            {"transcript_length": len(transcript)},
        )

        normalized = transcript.strip()

        if len(normalized) > self.MAX_CHARS:
            normalized = normalized[: self.MAX_CHARS]

        if len(normalized) > self.CHUNK_CHARS:
            normalized = self._merge_partial_summaries(normalized)

        prompt = extraction_prompt(normalized)
        response = _client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EXTRACTION_SCHEMA,
            ),
        )

        payload = json.loads(response.text or "{}")
        result = self._parse_payload(payload)

        pipeline_complete(
            "ai-notes.summarize",
            "Structured meeting notes extracted",
            {
                "title": result.title,
                "keyword_count": len(result.keywords),
            },
        )
        return result

    def _merge_partial_summaries(self, transcript: str) -> str:
        chunks = [
            transcript[index : index + self.CHUNK_CHARS]
            for index in range(0, len(transcript), self.CHUNK_CHARS)
        ]
        partials: list[str] = []

        for chunk in chunks:
            response = _client.models.generate_content(
                model=MODEL,
                contents=(
                    "Summarize this meeting transcript segment in plain text. "
                    "Keep decisions, owners, dates, and action items.\n\n"
                    f"{chunk}"
                ),
            )
            partials.append((response.text or "").strip())

        return "\n\n".join(part for part in partials if part)

    def _parse_payload(self, payload: dict) -> ExtractionResult:
        actionable_items: list[ActionableItem] = []

        for item in payload.get("actionable_items", []):
            status_raw = str(item.get("status", "pending")).lower()
            status = (
                TaskStatus.COMPLETED
                if status_raw in {"completed", "done", "finished"}
                else TaskStatus.PENDING
            )
            actionable_items.append(
                ActionableItem(
                    task=str(item.get("task", "")).strip(),
                    owner=str(item.get("owner", "")).strip(),
                    due_date=str(item.get("due_date", "")).strip(),
                    status=status,
                )
            )

        pending_tasks = [
            str(task).strip()
            for task in payload.get("pending_tasks", [])
            if str(task).strip()
        ]
        completed_tasks = [
            str(task).strip()
            for task in payload.get("completed_tasks", [])
            if str(task).strip()
        ]

        for item in actionable_items:
            if item.status == TaskStatus.COMPLETED:
                if item.task and item.task not in completed_tasks:
                    completed_tasks.append(item.task)
            elif item.task and item.task not in pending_tasks:
                pending_tasks.append(item.task)

        return ExtractionResult(
            title=str(payload.get("title", "Meeting Notes")).strip() or "Meeting Notes",
            summary=str(payload.get("summary", "")).strip(),
            keywords=[
                str(keyword).strip()
                for keyword in payload.get("keywords", [])
                if str(keyword).strip()
            ],
            actionable_items=actionable_items,
            pending_tasks=pending_tasks,
            completed_tasks=completed_tasks,
        )
