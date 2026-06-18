import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.utils.logger import logger


CHATS_DIR = Path("data/chats")


class ChatStore:

    def __init__(self, chats_dir: Path = CHATS_DIR):
        self.chats_dir = chats_dir
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, chat_id: str) -> Path:
        return self.chats_dir / f"{chat_id}.json"

    def _read_json(self, path: Path) -> dict | None:
        try:
            content = path.read_text(encoding="utf-8").strip()

            if not content:
                return None

            return json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable chat file %s: %s", path, exc)
            return None

    def list_chats(self) -> list[dict]:
        chats = []

        for file in sorted(self.chats_dir.glob("*.json")):
            if file.name.endswith(".tmp"):
                continue

            with self._lock:
                chat = self._read_json(file)

            if chat is not None:
                chats.append(chat)

        chats.sort(
            key=lambda chat: chat.get("updated_at", ""),
            reverse=True,
        )
        return chats

    def get_chat(self, chat_id: str) -> dict | None:
        path = self._path(chat_id)

        if not path.exists():
            return None

        with self._lock:
            return self._read_json(path)

    def create_chat(self, title: str = "New chat") -> dict:
        now = datetime.utcnow().isoformat()
        chat = {
            "id": str(uuid.uuid4()),
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

        self._save(chat)
        return chat

    def append_turn(
        self,
        chat_id: str,
        transcript: str,
        response: str,
    ) -> dict | None:
        with self._lock:
            chat = self._read_json(self._path(chat_id))

            if chat is None:
                return None

            chat["messages"].append(
                {"role": "user", "text": transcript}
            )

            if response:
                chat["messages"].append(
                    {"role": "assistant", "text": response}
                )

            if chat["title"] == "New chat" and transcript.strip():
                title = transcript.strip()
                chat["title"] = title[:48] + ("..." if len(title) > 48 else "")

            chat["updated_at"] = datetime.utcnow().isoformat()
            self._save_unlocked(chat)

        return chat

    def get_history(self, chat_id: str, limit: int = 5) -> list[dict]:
        chat = self.get_chat(chat_id)

        if chat is None:
            return []

        messages = chat.get("messages", [])
        turns = []

        for index in range(0, len(messages) - 1, 2):
            user_message = messages[index]
            assistant_message = messages[index + 1]

            if user_message.get("role") != "user":
                continue

            if assistant_message.get("role") != "assistant":
                continue

            turns.append(
                {
                    "transcript": user_message.get("text", ""),
                    "response": assistant_message.get("text", ""),
                }
            )

        return turns[-limit:]

    def delete_chat(self, chat_id: str) -> bool:
        path = self._path(chat_id)

        with self._lock:
            if not path.exists():
                return False

            path.unlink()
            tmp_path = path.with_suffix(".json.tmp")

            if tmp_path.exists():
                tmp_path.unlink()

        return True

    def _save(self, chat: dict) -> None:
        with self._lock:
            self._save_unlocked(chat)

    def _save_unlocked(self, chat: dict) -> None:
        path = self._path(chat["id"])
        tmp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(chat, indent=2)

        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
