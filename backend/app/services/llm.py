import logging

from google import genai
from google.genai.errors import APIError

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMServiceError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMService:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    @property
    def model(self) -> str:
        return self._model

    async def chat(self, message: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=message
            )
        except APIError as exc:
            logger.error("Gemini API error: %s", exc)
            retryable = exc.code in (429.503)
            raise LLMServiceError(f"Gagal menghubungi gemini:{exc}", retryable=retryable) from exc

        if not response.text:
            raise LLMServiceError("Gemini mengembalikan response kosong")

        return response.text

    async def chat_with_history(self, history: list[dict[str, str]]) -> str:
        contents = [
            {
                "role": "user" if turn["role"] == "user" else "model",
                "parts": [{"text": turn["content"]}],
            }
            for turn in history
        ]

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
            )
        except APIError as exc:
            logger.error("Gemini API error: %s", exc)
            retryable = exc.code in (429, 503)
            raise LLMServiceError(f"Gagal menghubungi Gemini: {exc}", retryable=retryable) from exc

        if not response.text:
            raise LLMServiceError("Gemini mengembalikan response kosong")

        return response.text


llm_service = LLMService()
