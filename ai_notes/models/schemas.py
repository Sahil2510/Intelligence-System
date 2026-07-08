from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class ActionableItem(BaseModel):
    task: str
    owner: str = ""
    due_date: str = ""
    status: TaskStatus = TaskStatus.PENDING


class TranscriptSegment(BaseModel):
    index: int
    transcript: str
    recorded_at: str


class NoteEmbeddings(BaseModel):
    title: list[float] = Field(default_factory=list)
    summary: list[float] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    title: str
    summary: str
    keywords: list[str] = Field(default_factory=list)
    actionable_items: list[ActionableItem] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    completed_tasks: list[str] = Field(default_factory=list)


class MeetingNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    title: str
    summary: str
    keywords: list[str] = Field(default_factory=list)
    actionable_items: list[ActionableItem] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    completed_tasks: list[str] = Field(default_factory=list)
    raw_transcript: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)
    embeddings: NoteEmbeddings = Field(default_factory=NoteEmbeddings)
    status: Literal["processing", "completed"] = "completed"
    started_at: str = ""
    ended_at: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_storage_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_storage_dict(cls, payload: dict) -> MeetingNote:
        return cls.model_validate(payload)


class SessionChunkRef(BaseModel):
    index: int
    path: str
    mime_type: str = "audio/webm"
    recorded_at: str


class MeetingSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    status: Literal["active", "processing", "completed"] = "active"
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    ended_at: str = ""
    chunks: list[SessionChunkRef] = Field(default_factory=list)
    segments: list[TranscriptSegment] = Field(default_factory=list)
    note_id: str = ""
