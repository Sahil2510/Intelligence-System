from google import genai
from google.genai import types

from app.config import (
    GEMINI_API_KEY,
    GEMINI_EMBEDDING_DIMENSION,
    GEMINI_EMBEDDING_MODEL,
)
from app.utils.pipeline_log import pipeline_complete, pipeline_start

_client = genai.Client(api_key=GEMINI_API_KEY)


class NoteEmbedder:

    def __init__(
        self,
        *,
        model: str = GEMINI_EMBEDDING_MODEL,
        dimension: int = GEMINI_EMBEDDING_DIMENSION,
    ):
        self.model = model
        self.dimension = dimension

    def _extract_vector(self, response) -> list[float]:
        embeddings = response.embeddings or []

        if not embeddings:
            raise ValueError("Gemini returned no embeddings")

        values = embeddings[0].values

        if values is None:
            raise ValueError("Gemini embedding values are empty")

        return list(values)

    def embed_document(
        self,
        text: str,
        *,
        title: str | None = None,
    ) -> list[float]:
        pipeline_start(
            "ai-notes.embed.document",
            "Embedding meeting note document",
            {
                "model": self.model,
                "text_length": len(text),
                "has_title": bool(title),
            },
        )

        config = types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=self.dimension,
        )

        if title:
            config.title = title

        response = _client.models.embed_content(
            model=self.model,
            contents=text,
            config=config,
        )
        vector = self._extract_vector(response)

        pipeline_complete(
            "ai-notes.embed.document",
            "Meeting note document embedded",
            {"dimensions": len(vector)},
        )
        return vector

    def embed_title(self, title: str) -> list[float]:
        return self.embed_document(title, title=title)

    def embed_summary(self, summary: str, keywords: list[str] | None = None) -> list[float]:
        keyword_text = ", ".join(keywords or [])
        contents = summary

        if keyword_text:
            contents = f"{summary}\nKeywords: {keyword_text}"

        return self.embed_document(contents)

    def embed_query(self, query: str) -> list[float]:
        pipeline_start(
            "ai-notes.embed.query",
            "Embedding meeting note query",
            {"model": self.model, "query_length": len(query)},
        )

        response = _client.models.embed_content(
            model=self.model,
            contents=query,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=self.dimension,
            ),
        )
        vector = self._extract_vector(response)

        pipeline_complete(
            "ai-notes.embed.query",
            "Meeting note query embedded",
            {"dimensions": len(vector)},
        )
        return vector
