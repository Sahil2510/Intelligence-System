import json
import os
import threading
from datetime import datetime
from pathlib import Path

from ai_notes.models.schemas import MeetingNote
from app.utils.logger import logger

NOTES_DIR = Path("data/notes")


class NoteStore:

    def __init__(self, notes_dir: Path = NOTES_DIR):
        self.notes_dir = notes_dir
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, note_id: str) -> Path:
        return self.notes_dir / f"{note_id}.json"

    def _read_json(self, path: Path) -> dict | None:
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return None
            return json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable note file %s: %s", path, exc)
            return None

    def save(self, note: MeetingNote) -> MeetingNote:
        with self._lock:
            self._save_unlocked(note)
        return note

    def get(self, note_id: str) -> MeetingNote | None:
        path = self._path(note_id)
        if not path.exists():
            return None
        with self._lock:
            payload = self._read_json(path)
        if payload is None:
            return None
        return MeetingNote.from_storage_dict(payload)

    def list_notes(self, user_id: str | None = None) -> list[MeetingNote]:
        notes: list[MeetingNote] = []

        for file in sorted(self.notes_dir.glob("*.json")):
            if file.name == "index.json" or file.name.endswith(".tmp"):
                continue

            with self._lock:
                payload = self._read_json(file)

            if payload is None:
                continue

            note = MeetingNote.from_storage_dict(payload)
            if user_id and note.user_id != user_id:
                continue
            notes.append(note)

        notes.sort(
            key=lambda item: item.ended_at or item.created_at,
            reverse=True,
        )
        return notes

    def delete(self, note_id: str) -> bool:
        path = self._path(note_id)
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
            tmp_path = path.with_suffix(".json.tmp")
            if tmp_path.exists():
                tmp_path.unlink()
        return True

    def _save_unlocked(self, note: MeetingNote) -> None:
        path = self._path(note.id)
        tmp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(note.to_storage_dict(), indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, path)
