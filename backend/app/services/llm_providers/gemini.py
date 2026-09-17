"""Adapter Gemini -- satu-satunya file yang boleh import `google.genai`.

Ini murni pemindahan logika yang sebelumnya ada langsung di `LLMService`
(sebelum Bagian 18: Model-Agnostic Architecture dikerjakan). Perilakunya
sengaja dibuat SAMA PERSIS dengan sebelumnya -- ini refactor struktural,
bukan perubahan perilaku.
"""

import logging
import time

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from app.core.logging_config import log_event
from app.services.llm_providers.base import GenerationResult, ProviderError, TokenUsage
from app.services.tools.registry import AVAILABLE_TOOLS

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_REQUEST = 8

_ROLE_TO_GEMINI = {"user": "user", "assistant": "model"}


def _to_gemini_contents(messages: list[dict[str, str]]) -> list[dict]:
    return [
        {
            "role": _ROLE_TO_GEMINI.get(m["role"], "user"),
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]


def _extract_usage(response) -> TokenUsage:
    """Ambil token usage dari response Gemini secara defensif.

    `usage_metadata` bisa saja tidak ada (mis. versi SDK berbeda, atau
    response mock di test) -- observability tidak boleh sampai menjadi
    penyebab request asli meledak, jadi field yang tidak ada cukup jadi
    None, bukan raise.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        total_tokens=getattr(usage, "total_token_count", None),
    )


def _as_structured[T: BaseModel](response, model_cls: type[T]) -> T | None:
    """Validasi tipe `response.parsed` dari Gemini secara eksplisit. SDK
    mengetik `response.parsed` secara generik (`BaseModel | Dict | Enum | None`)
    karena dia tidak tahu skema spesifik yang kita minta lewat
    `response_schema`. Mengklaim tipenya lewat anotasi variabel saja TIDAK
    memvalidasi apapun secara runtime -- fungsi ini memastikan validasi itu
    benar-benar terjadi.
    """
    parsed = getattr(response, "parsed", None)
    return parsed if isinstance(parsed, model_cls) else None


def _extract_tool_calls(response) -> list[str]:
    """Ambil nama tool yang dipanggil Gemini lewat automatic function calling.

    Gemini menyimpan riwayat ini di `automatic_function_calling_history`.
    Mengembalikan nama tool sesuai urutan pemanggilan, [] kalau tidak ada.
    """
    tool_calls: list[str] = []
    history = getattr(response, "automatic_function_calling_history", None) or []

    for content in history:
        for part in getattr(content, "parts", None) or []:
            function_call = getattr(part, "function_call", None)
            if function_call is None:
                continue
            name = getattr(function_call, "name", None)
            if name:
                tool_calls.append(name)

    return tool_calls


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        use_tools: bool = False,
    ) -> GenerationResult:
        # Kasus umum "satu prompt saja" (mayoritas pemanggil) dikirim sebagai
        # string polos, bukan list -- ini sama persis dengan perilaku lama
        # (contents=message), bukan sekadar penyederhanaan baru.
        if len(messages) == 1 and messages[0]["role"] == "user" and not system_instruction:
            contents: str | list[dict] = messages[0]["content"]
        else:
            contents = _to_gemini_contents(messages)

        config_kwargs: dict = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema
        if use_tools:
            config_kwargs["tools"] = AVAILABLE_TOOLS
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=MAX_TOOL_CALLS_PER_REQUEST
            )
        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        start = time.perf_counter()
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except APIError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log_event(
                logger,
                "llm_call",
                provider="gemini",
                model=self._model,
                duration_ms=duration_ms,
                success=False,
                error=str(exc),
            )
            retryable = exc.code in (429, 503)
            raise ProviderError(str(exc), retryable=retryable) from exc

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        usage = _extract_usage(response)
        tools_called = _extract_tool_calls(response)
        log_event(
            logger,
            "llm_call",
            provider="gemini",
            model=self._model,
            duration_ms=duration_ms,
            success=True,
            tools_called=tools_called,
            prompt_tokens=usage.prompt_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )

        parsed = _as_structured(response, response_schema) if response_schema is not None else None

        return GenerationResult(
            text=response.text or "",
            parsed=parsed,
            usage=usage,
            tools_called=tools_called,
        )