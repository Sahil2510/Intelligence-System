import re

_SENTENCE_END = re.compile(r"(?<=[.!?।\n])\s+")


class SentenceBuffer:

    def __init__(self) -> None:
        self._buffer = ""

    def push(self, text: str) -> list[str]:
        if not text:
            return []

        self._buffer += text
        sentences: list[str] = []
        parts = _SENTENCE_END.split(self._buffer)

        if len(parts) > 1:
            for part in parts[:-1]:
                cleaned = part.strip()
                if cleaned:
                    sentences.append(cleaned)

            self._buffer = parts[-1]

        return sentences

    def flush(self) -> str | None:
        cleaned = self._buffer.strip()
        self._buffer = ""

        if cleaned:
            return cleaned

        return None
