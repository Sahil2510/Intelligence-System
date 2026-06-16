from __future__ import annotations

import threading
from typing import Any

from app.config import (
    DEFAULT_USER_ID,
    MEM0_API_KEY,
    MEM0_SEARCH_LIMIT,
)
from app.utils.pipeline_log import pipeline_complete, pipeline_error, pipeline_start


class LongTermMemory:

    def __init__(self):
        self.enabled = bool(MEM0_API_KEY)
        self.search_limit = MEM0_SEARCH_LIMIT
        self._client = None
        self._lock = threading.Lock()

    def _get_client(self):
        if not self.enabled:
            return None

        if self._client is None:
            with self._lock:
                if self._client is None:
                    from mem0 import MemoryClient

                    self._client = MemoryClient(api_key=MEM0_API_KEY)

        return self._client

    @staticmethod
    def _preview(text: str, limit: int = 120) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    @staticmethod
    def _normalize_search_results(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, dict):
            items = raw.get("results") or raw.get("memories") or []
        elif isinstance(raw, list):
            items = raw
        else:
            items = []

        normalized: list[dict[str, Any]] = []

        for item in items:
            if isinstance(item, str):
                normalized.append({"memory": item, "score": None, "id": None})
                continue

            if not isinstance(item, dict):
                continue

            normalized.append(
                {
                    "memory": (
                        item.get("memory")
                        or item.get("text")
                        or item.get("content")
                        or str(item)
                    ),
                    "score": item.get("score"),
                    "id": item.get("id"),
                }
            )

        return normalized

    def search(
        self,
        user_id: str,
        query: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        resolved_user_id = user_id or DEFAULT_USER_ID
        resolved_limit = limit or self.search_limit

        pipeline_start(
            "memory.ltm.load",
            "Searching long-term memory in Mem0",
            {
                "backend": "mem0",
                "user_id": resolved_user_id,
                "query_preview": self._preview(query),
                "limit": resolved_limit,
                "enabled": self.enabled,
            },
        )

        if not self.enabled:
            pipeline_complete(
                "memory.ltm.load",
                "Mem0 long-term memory skipped (MEM0_API_KEY not set)",
                {
                    "backend": "mem0",
                    "user_id": resolved_user_id,
                    "memory_count": 0,
                    "memories": [],
                },
            )
            return []

        try:
            client = self._get_client()
            raw = client.search(
                query=query,
                user_id=resolved_user_id,
                limit=resolved_limit,
            )
            memories = self._normalize_search_results(raw)

            pipeline_complete(
                "memory.ltm.load",
                "Long-term memory loaded from Mem0",
                {
                    "backend": "mem0",
                    "user_id": resolved_user_id,
                    "query_preview": self._preview(query),
                    "memory_count": len(memories),
                    "memories": [
                        {
                            "id": item.get("id"),
                            "score": item.get("score"),
                            "memory_preview": self._preview(
                                str(item.get("memory", ""))
                            ),
                        }
                        for item in memories
                    ],
                },
            )
            return memories
        except Exception as exc:
            pipeline_error(
                "memory.ltm.load",
                "Failed to search long-term memory in Mem0",
                {
                    "backend": "mem0",
                    "user_id": resolved_user_id,
                    "query_preview": self._preview(query),
                    "error": str(exc),
                },
            )
            return []

    def add_turn(
        self,
        user_id: str,
        transcript: str,
        response: str,
        *,
        chat_id: str | None = None,
        intent: str | None = None,
    ) -> None:
        resolved_user_id = user_id or DEFAULT_USER_ID

        if not transcript.strip():
            return

        self._add_turn(
            resolved_user_id,
            transcript,
            response,
            chat_id,
            intent,
        )

    def _add_turn(
        self,
        user_id: str,
        transcript: str,
        response: str,
        chat_id: str | None,
        intent: str | None,
    ) -> None:
        pipeline_start(
            "memory.ltm.save",
            "Saving turn to Mem0 long-term memory",
            {
                "backend": "mem0",
                "user_id": user_id,
                "chat_id": chat_id,
                "intent": intent,
                "transcript_preview": self._preview(transcript),
                "response_preview": self._preview(response),
                "enabled": self.enabled,
            },
        )

        if not self.enabled:
            pipeline_complete(
                "memory.ltm.save",
                "Mem0 long-term memory save skipped (MEM0_API_KEY not set)",
                {
                    "backend": "mem0",
                    "user_id": user_id,
                    "saved": False,
                },
            )
            return

        messages = [{"role": "user", "content": transcript}]

        if response.strip():
            messages.append({"role": "assistant", "content": response})

        metadata = {
            "source": "luvio-playground",
        }

        if chat_id:
            metadata["chat_id"] = chat_id

        if intent:
            metadata["intent"] = intent

        try:
            client = self._get_client()
            result = client.add(
                messages=messages,
                user_id=user_id,
                metadata=metadata,
            )

            memory_ids: list[str] = []

            if isinstance(result, dict):
                if result.get("id"):
                    memory_ids.append(str(result["id"]))

                for item in result.get("results") or []:
                    if isinstance(item, dict) and item.get("id"):
                        memory_ids.append(str(item["id"]))

            pipeline_complete(
                "memory.ltm.save",
                "Turn saved to Mem0 long-term memory",
                {
                    "backend": "mem0",
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "intent": intent,
                    "memory_ids": memory_ids,
                    "message_count": len(messages),
                    "saved": True,
                },
            )
        except Exception as exc:
            pipeline_error(
                "memory.ltm.save",
                "Failed to save turn to Mem0 long-term memory",
                {
                    "backend": "mem0",
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "intent": intent,
                    "error": str(exc),
                },
            )
