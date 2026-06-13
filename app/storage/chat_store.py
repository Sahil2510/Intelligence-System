import json
import uuid
from datetime import datetime
from pathlib import Path


CHATS_DIR = Path("data/chats")


class ChatStore:

    def __init__(self, chats_dir: Path = CHATS_DIR):
        self.chats_dir = chats_dir
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chat_id: str) -> Path:
        return self.chats_dir / f"{chat_id}.json"

    def list_chats(self) -> list[dict]:
        chats = []

        for file in self.chats_dir.glob("*.json"):
            with file.open("r", encoding="utf-8") as handle:
                chats.append(json.load(handle))

        chats.sort(
            key=lambda chat: chat.get("updated_at", ""),
            reverse=True,
        )
        return chats

    def get_chat(self, chat_id: str) -> dict | None:
        path = self._path(chat_id)

        if not path.exists():
            return None

        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

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
        chat = self.get_chat(chat_id)

        if chat is None:
            return None

        chat["messages"].append(
            {"role": "user", "text": transcript}
        )
        chat["messages"].append(
            {"role": "assistant", "text": response}
        )

        if chat["title"] == "New chat" and transcript.strip():
            title = transcript.strip()
            chat["title"] = title[:48] + ("..." if len(title) > 48 else "")

        chat["updated_at"] = datetime.utcnow().isoformat()
        self._save(chat)
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

        if not path.exists():
            return False

        path.unlink()
        return True

    def _save(self, chat: dict) -> None:
        with self._path(chat["id"]).open("w", encoding="utf-8") as handle:
            json.dump(chat, handle, indent=2)
