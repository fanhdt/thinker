from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types
from google.genai.errors import APIError

from app.services.llm_providers.base import ProviderError
from app.services.llm_providers.gemini import GeminiProvider, _extract_tool_calls


def _build_provider_with_fake_client(api_error: APIError) -> GeminiProvider:
    """Buat GeminiProvider tanpa melalui __init__ (jadi tidak butuh API key asli).

    __new__ melewati __init__ sepenuhnya, jadi kita bisa suntik `_client` palsu
    yang perilakunya kita kontrol penuh di test.
    """
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._model = "fake-model"

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(side_effect=api_error)
    provider._client = fake_client

    return provider


@pytest.mark.parametrize("status_code", [429, 503])
async def test_generate_marks_error_as_retryable_for_429_and_503(status_code):
    """Ini test yang seharusnya menangkap bug `exc.code in (429.503)` di masa lalu.

    Sebelum fix: baris itu adalah `exc.code in (429.503)` -- (429.503) adalah
    float, bukan tuple, jadi `in` akan melempar TypeError, BUKAN ProviderError.
    Test ini gagal dengan TypeError sebelum fix, dan lulus setelah fix.
    """
    api_error = APIError(status_code, {"message": "rate limited atau service unavailable"})
    provider = _build_provider_with_fake_client(api_error)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate([{"role": "user", "content": "halo"}])

    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status_code", [400, 401, 404])
async def test_generate_marks_error_as_not_retryable_for_client_errors(status_code):
    """Error 4xx selain 429 (mis. bad request, auth) tidak boleh dianggap retryable --
    mengulang request yang salah/tidak sah tidak akan pernah berhasil.
    """
    api_error = APIError(status_code, {"message": "client error"})
    provider = _build_provider_with_fake_client(api_error)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate([{"role": "user", "content": "halo"}])

    assert exc_info.value.retryable is False


async def test_generate_returns_empty_text_when_gemini_returns_empty_response():
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._model = "fake-model"

    fake_response = MagicMock()
    fake_response.text = ""
    fake_response.usage_metadata = None
    fake_response.automatic_function_calling_history = None
    fake_response.parsed = None

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(return_value=fake_response)
    provider._client = fake_client

    result = await provider.generate([{"role": "user", "content": "halo"}])

    # GeminiProvider sendiri tidak menentukan "response kosong itu error" --
    # itu keputusan bisnis LLMService (lihat test_llm_service.py). Provider
    # cuma melaporkan text kosong apa adanya.
    assert result.text == ""


def test_extract_tool_calls_returns_empty_list_when_no_history():
    response = MagicMock(spec=[])  # tidak ada atribut apa pun, mirip response tanpa AFC
    assert _extract_tool_calls(response) == []


def test_extract_tool_calls_collects_function_call_names_in_order():
    """Regresi tak langsung untuk Bagian 21 ('selected tools'): sebelumnya
    tidak ada visibilitas sama sekali tool apa yang benar-benar dipanggil
    Gemini lewat automatic function calling."""
    history = [
        types.Content(
            role="model",
            parts=[
                types.Part(function_call=types.FunctionCall(name="calculator", args={})),
                types.Part(text="hasil kalkulasi: 4"),
            ],
        ),
        types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name="datetime_now", args={}))],
        ),
    ]
    response = MagicMock(automatic_function_calling_history=history)

    assert _extract_tool_calls(response) == ["calculator", "datetime_now"]