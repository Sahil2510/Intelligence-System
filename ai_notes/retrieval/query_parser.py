from __future__ import annotations

import re
from enum import Enum


class QueryMode(str, Enum):
    LATEST = "latest"
    SEMANTIC = "semantic"
    PENDING_TASKS = "pending_tasks"
    COMPLETED_TASKS = "completed_tasks"


_LATEST_PATTERNS = (
    r"\blatest meeting\b",
    r"\blast meeting\b",
    r"\bmost recent meeting\b",
    r"\brecent meeting\b",
    r"\bwhat happened in the meeting\b",
    r"\bwhat happened in the last\b",
    r"\bwhat happened in the latest\b",
)

_PENDING_PATTERNS = (
    r"\bpending tasks?\b",
    r"\bopen tasks?\b",
    r"\baction items?\b",
    r"\btodo\b",
    r"\bto do\b",
    r"\bwhat do i need to do\b",
)

_COMPLETED_PATTERNS = (
    r"\bcompleted tasks?\b",
    r"\bdone tasks?\b",
    r"\bfinished tasks?\b",
)


def parse_meeting_query(transcript: str) -> tuple[QueryMode, str]:
    cleaned = transcript.strip().lower()

    if any(re.search(pattern, cleaned) for pattern in _LATEST_PATTERNS):
        return QueryMode.LATEST, cleaned

    if any(re.search(pattern, cleaned) for pattern in _PENDING_PATTERNS):
        return QueryMode.PENDING_TASKS, cleaned

    if any(re.search(pattern, cleaned) for pattern in _COMPLETED_PATTERNS):
        return QueryMode.COMPLETED_TASKS, cleaned

    return QueryMode.SEMANTIC, cleaned
