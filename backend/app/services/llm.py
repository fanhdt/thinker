import logging

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class MemoryExtraction(BaseModel):
    has_memory: bool
    fact: str | None = None


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
                model=self._model,
                contents=message,
            )
        except APIError as exc:
            logger.error("Gemini API error: %s", exc)
            retryable = exc.code in (429.503)
            raise LLMServiceError(f"Gagal menghubungi gemini:{exc}", retryable=retryable) from exc

        if not response.text:
            raise LLMServiceError("Gemini mengembalikan response kosong")

        return response.text

    async def chat_with_history(
        self, history: list[dict[str, str]], *, system_instruction: str | None = None
    ) -> str:
        contents = [
            {
                "role": "user" if turn["role"] == "user" else "model",
                "parts": [{"text": turn["content"]}],
            }
            for turn in history
        ]

        config = (
            types.GenerateContentConfig(system_instruction=system_instruction)
            if system_instruction
            else None
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except APIError as exc:
            logger.error("Gemini API error: %s", exc)
            retryable = exc.code in (429, 503)
            raise LLMServiceError(f"Gagal menghubungi Gemini: {exc}", retryable=retryable) from exc

        if not response.text:
            raise LLMServiceError("Gemini mengembalikan response kosong")

        return response.text

    async def extract_fact(self, message: str) -> str | None:
        prompt = (
            "Analisis pesan berikut dari user sebuah asisten AI personal.\n"
            "Apakah pesan ini mengandung FAKTA PERSONAL yang layak diingat "
            "jangka panjang (preferensi, kondisi kesehatan, pekerjaan, "
            "hubungan, kebiasaan, dsb)? Pertanyaan biasa atau basa-basi "
            "BUKAN fakta yang perlu diingat.\n\n"
            f'Pesan: "{message}"\n\n'
            "Kalau ADA fakta, tulis ulang sebagai satu kalimat singkat & "
            'netral berperspektif orang ketiga (mis. "User alergi kacang."), '
            "bukan mengutip mentah."
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MemoryExtraction,
                ),
            )
        except APIError as exc:
            logger.error("Gemini extraction error :%s", exc)
            raise LLMServiceError(f"Gagal ekstraksi memori :{exc}") from exc

        result: MemoryExtraction | None = response.parsed
        if result and result.has_memory and result.fact:
            return result.fact
        return None


llm_service = LLMService()
