import json
from typing import Any

import redis

from app.config import REDIS_STM_MAX_MESSAGES, REDIS_STM_TTL_SECONDS, REDIS_URL
from app.utils.pipeline_log import pipeline_complete, pipeline_error, pipeline_start


class RedisShortTermMemory:

    KEY_PREFIX = "luvio:stm:chat"

    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_url = redis_url
        self.max_messages = REDIS_STM_MAX_MESSAGES
        self.ttl_seconds = REDIS_STM_TTL_SECONDS
        self._client: redis.Redis | None = None

    def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
            )
        return self._client

    def _key(self, chat_id: str) -> str:
        return f"{self.KEY_PREFIX}:{chat_id}"

    @staticmethod
    def _preview(text: str, limit: int = 120) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    @staticmethod
    def _messages_to_turns(messages: list[dict]) -> list[dict]:
        turns: list[dict] = []

        index = 0
        while index < len(messages):
            user_message = messages[index]
            if user_message.get("role") != "user":
                index += 1
                continue

            transcript = user_message.get("text", "")
            response = ""

            if index + 1 < len(messages):
                assistant_message = messages[index + 1]
                if assistant_message.get("role") == "assistant":
                    response = assistant_message.get("text", "")
                    index += 2
                else:
                    index += 1
            else:
                index += 1

            turns.append(
                {
                    "transcript": transcript,
                    "response": response,
                }
            )

        return turns

    def get_history(
        self,
        chat_id: str,
        limit: int = 5,
    ) -> list[dict]:
        redis_key = self._key(chat_id)

        pipeline_start(
            "memory.stm.load",
            "Loading short-term memory from Redis",
            {
                "backend": "redis",
                "chat_id": chat_id,
                "redis_key": redis_key,
                "turn_limit": limit,
                "redis_url": self.redis_url,
            },
        )

        try:
            client = self._get_client()
            raw_messages = client.lrange(redis_key, 0, -1)
            messages = [
                json.loads(item)
                for item in raw_messages
            ]
            turns = self._messages_to_turns(messages)
            history = turns[-limit:]

            pipeline_complete(
                "memory.stm.load",
                "Short-term memory loaded from Redis",
                {
                    "backend": "redis",
                    "chat_id": chat_id,
                    "redis_key": redis_key,
                    "message_count": len(messages),
                    "turn_count": len(history),
                    "turns": [
                        {
                            "transcript_preview": self._preview(
                                turn.get("transcript", "")
                            ),
                            "response_preview": self._preview(
                                turn.get("response", "")
                            ),
                        }
                        for turn in history
                    ],
                },
            )
            return history
        except Exception as exc:
            pipeline_error(
                "memory.stm.load",
                "Failed to load short-term memory from Redis",
                {
                    "backend": "redis",
                    "chat_id": chat_id,
                    "redis_key": redis_key,
                    "error": str(exc),
                },
            )
            raise

    def append_turn(
        self,
        chat_id: str,
        transcript: str,
        response: str,
    ) -> dict[str, Any]:
        redis_key = self._key(chat_id)

        pipeline_start(
            "memory.stm.save",
            "Saving turn to Redis short-term memory",
            {
                "backend": "redis",
                "chat_id": chat_id,
                "redis_key": redis_key,
                "transcript_preview": self._preview(transcript),
                "response_preview": self._preview(response),
                "ttl_seconds": self.ttl_seconds,
            },
        )

        try:
            client = self._get_client()
            pipe = client.pipeline()
            pipe.rpush(
                redis_key,
                json.dumps({"role": "user", "text": transcript}),
            )

            if response:
                pipe.rpush(
                    redis_key,
                    json.dumps({"role": "assistant", "text": response}),
                )

            pipe.ltrim(redis_key, -self.max_messages, -1)

            if self.ttl_seconds > 0:
                pipe.expire(redis_key, self.ttl_seconds)

            pipe.execute()
            message_count = client.llen(redis_key)

            payload = {
                "backend": "redis",
                "chat_id": chat_id,
                "redis_key": redis_key,
                "message_count": message_count,
                "max_messages": self.max_messages,
                "ttl_seconds": self.ttl_seconds,
            }

            pipeline_complete(
                "memory.stm.save",
                "Turn saved to Redis short-term memory",
                payload,
            )
            return payload
        except Exception as exc:
            pipeline_error(
                "memory.stm.save",
                "Failed to save turn to Redis short-term memory",
                {
                    "backend": "redis",
                    "chat_id": chat_id,
                    "redis_key": redis_key,
                    "error": str(exc),
                },
            )
            raise

    def ping(self) -> bool:
        try:
            return bool(self._get_client().ping())
        except Exception:
            return False
