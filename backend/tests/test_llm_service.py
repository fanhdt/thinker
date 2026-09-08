from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai.errors import APIError

from app.services.llm import LLMService, LLMServiceError


def _build_service_with_fake_client(api_error: APIError) -> LLMService:
    """Buat LLMService tanpa melalui __init__ (jadi tidak butuh gemini_api_key asli).

    __new__ melewati __init__ sepenuhnya, jadi kita bisa suntik `_client` palsu
    yang perilakunya kita kontrol penuh di test.
    """
    service = LLMService.__new__(LLMService)
    service._model = "fake-model"

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(side_effect=api_error)
    service._client = fake_client

    return service


@pytest.mark.parametrize("status_code", [429, 503])
async def test_chat_marks_error_as_retryable_for_429_and_503(status_code):
    """Ini test yang seharusnya menangkap bug `exc.code in (429.503)` di masa lalu.

    Sebelum fix: baris itu adalah `exc.code in (429.503)` -- (429.503) adalah
    float, bukan tuple, jadi `in` akan melempar TypeError, BUKAN LLMServiceError.
    Test ini gagal dengan TypeError sebelum fix, dan lulus setelah fix.
    """
    api_error = APIError(status_code, {"message": "rate limited atau service unavailable"})
    service = _build_service_with_fake_client(api_error)

    with pytest.raises(LLMServiceError) as exc_info:
        await service.chat("halo")

    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status_code", [400, 401, 404])
async def test_chat_marks_error_as_not_retryable_for_client_errors(status_code):
    """Error 4xx selain 429 (mis. bad request, auth) tidak boleh dianggap retryable --
    mengulang request yang salah/tidak sah tidak akan pernah berhasil.
    """
    api_error = APIError(status_code, {"message": "client error"})
    service = _build_service_with_fake_client(api_error)

    with pytest.raises(LLMServiceError) as exc_info:
        await service.chat("halo")

    assert exc_info.value.retryable is False


async def test_chat_raises_when_gemini_returns_empty_response():
    service = LLMService.__new__(LLMService)
    service._model = "fake-model"

    fake_response = MagicMock()
    fake_response.text = ""

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(return_value=fake_response)
    service._client = fake_client

    with pytest.raises(LLMServiceError):
        await service.chat("halo")