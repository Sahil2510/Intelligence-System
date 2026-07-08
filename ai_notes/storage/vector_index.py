from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import numpy as np

from app.utils.logger import logger

INDEX_PATH = Path("data/notes/index.json")


class VectorIndex:

    def __init__(self, index_path: Path = INDEX_PATH):
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        if not self.index_path.exists():
            return []

        try:
            content = self.index_path.read_text(encoding="utf-8").strip()
            if not content:
                return []
            payload = json.loads(content)
            return payload.get("entries", [])
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read vector index: %s", exc)
            return []

    def _save(self, entries: list[dict]) -> None:
        tmp_path = self.index_path.with_suffix(".json.tmp")
        payload = json.dumps({"entries": entries}, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self.index_path)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0

        vec_a = np.array(a, dtype=np.float64)
        vec_b = np.array(b, dtype=np.float64)

        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

    def upsert(
        self,
        note_id: str,
        *,
        title_vector: list[float],
        summary_vector: list[float],
        user_id: str,
        created_at: str,
    ) -> None:
        with self._lock:
            entries = self._load()
            entries = [entry for entry in entries if entry.get("note_id") != note_id]
            entries.append(
                {
                    "note_id": note_id,
                    "user_id": user_id,
                    "title_vector": title_vector,
                    "summary_vector": summary_vector,
                    "created_at": created_at,
                }
            )
            self._save(entries)

    def remove(self, note_id: str) -> None:
        with self._lock:
            entries = self._load()
            entries = [entry for entry in entries if entry.get("note_id") != note_id]
            self._save(entries)

    def search(
        self,
        query_vector: list[float],
        *,
        user_id: str | None = None,
        limit: int = 3,
        title_weight: float = 0.4,
        summary_weight: float = 0.6,
    ) -> list[tuple[str, float]]:
        entries = self._load()
        scored: list[tuple[str, float]] = []

        for entry in entries:
            if user_id and entry.get("user_id") != user_id:
                continue

            title_score = self._cosine_similarity(
                query_vector,
                entry.get("title_vector", []),
            )
            summary_score = self._cosine_similarity(
                query_vector,
                entry.get("summary_vector", []),
            )
            score = (title_weight * title_score) + (summary_weight * summary_score)
            scored.append((entry["note_id"], score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]
