import re

_SENTENCE_END = re.compile(r"(?<=[.!?।\n])\s+")


class SpeakBuffer:
    """Buffer streamed tokens and emit speakable chunks early for TTS."""

    MIN_CHARS = 10
    MAX_CHARS = 72

    def __init__(self) -> None:
        self._buffer = ""

    def push(self, text: str) -> list[str]:
        if not text:
            return []

        self._buffer += text
        return self._extract_ready()

    def _extract_ready(self) -> list[str]:
        chunks: list[str] = []

        while self._buffer:
            parts = _SENTENCE_END.split(self._buffer, maxsplit=1)
            if len(parts) > 1 and parts[0].strip():
                chunks.append(parts[0].strip())
                self._buffer = parts[1]
                continue

            stripped = self._buffer.lstrip()
            if not stripped:
                self._buffer = ""
                break

            if len(stripped) >= self.MAX_CHARS:
                split_at = stripped.rfind(" ", 0, self.MAX_CHARS)
                if split_at < self.MIN_CHARS:
                    split_at = self.MAX_CHARS
                chunk = stripped[:split_at].strip()
                if chunk:
                    chunks.append(chunk)
                    self._buffer = stripped[split_at:].lstrip()
                    continue
                break

            boundary = self._find_clause_boundary(stripped)
            if boundary is not None and boundary >= self.MIN_CHARS:
                chunk = stripped[:boundary].strip()
                if chunk:
                    chunks.append(chunk)
                    self._buffer = stripped[boundary:].lstrip()
                    continue
                break

            if len(stripped) >= self.MIN_CHARS:
                space_at = self._word_boundary_after(stripped, self.MIN_CHARS)
                if space_at is not None:
                    chunk = stripped[:space_at].strip()
                    if chunk:
                        chunks.append(chunk)
                        self._buffer = stripped[space_at:].lstrip()
                        continue

            break

        return chunks

    @staticmethod
    def _find_clause_boundary(text: str) -> int | None:
        best = None

        for marker in (".", "?", "!", "।", "\n", ",", ";", ":"):
            idx = text.find(marker)
            if idx != -1:
                end = idx + 1
                if best is None or end < best:
                    best = end

        return best

    @staticmethod
    def _word_boundary_after(text: str, min_chars: int) -> int | None:
        idx = text.find(" ", min_chars)
        return idx if idx != -1 else None

    def flush(self) -> str | None:
        cleaned = self._buffer.strip()
        self._buffer = ""

        if cleaned:
            return cleaned

        return None


# Backward-compatible alias
SentenceBuffer = SpeakBuffer
