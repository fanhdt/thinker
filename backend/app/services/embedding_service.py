import logging

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.config import settings
from app.services.llm import LLMServiceError

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768


class EmbeddingService:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def embed_document(self, text: str) -> list[float]:
        return await self._embed(text, task_type="RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed(text, task_type="RETRIEVAL_QUERY")

    async def _embed(self, text: str, *, task_type:str) -> list[float]:
        try:
            response = await self._client.aio.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=EMBEDDING_DIMENSIONS,
                ),
            )
        except APIError as exc:
            logger.error("Gemin embedding error: %s", exc)
            raise LLMServiceError(f"gagal membuat embedding :{exc}") from exc

        embeddings = response.embeddings
        if not embeddings:
            raise LLMServiceError("Gemini mengembalikan embedding kosong (tidak ada embeddings)")

        values = embeddings[0].values
        if values is None:
            raise LLMServiceError("Gemini mengembalikan embedding kosong (tidak ada embeddings)")
        return values


embedding_service = EmbeddingService()
