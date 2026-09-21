"""Adapter untuk semua provider yang API-nya kompatibel dengan format OpenAI
-- OpenAI sendiri, Groq, DeepSeek. Bedanya cuma `base_url`, `api_key`, dan
`model`; kode di file ini SAMA untuk ketiganya. Ini persis maksud "Idealnya
cukup mengganti configuration untuk berpindah model" di master prompt:
provider baru yang API-nya kompatibel = konfigurasi baru, bukan kode baru.

Catatan jujur: file ini belum diverifikasi ke API sungguhan (perlu dites
langsung dengan API key masing-masing provider). Kalau ada perbedaan
perilaku (mis. dukungan tool-calling atau bentuk JSON mode yang sedikit
beda di Groq/DeepSeek dibanding OpenAI asli), itu akan muncul sebagai
`ProviderError` atau parsing gagal di percobaan pertama -- bukan gagal diam-diam.
"""

import json
import logging
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

from openai import APIError as OpenAIAPIError
from openai import AsyncOpenAI, omit
from pydantic import BaseModel, ValidationError

from app.core.logging_config import log_event
from app.services.llm_providers.base import GenerationResult, ProviderError, TokenUsage
from app.services.llm_providers.tool_schema import function_to_openai_schema
from app.services.tools.registry import AVAILABLE_TOOLS

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

logger = logging.getLogger(__name__)

MAX_TOOL_CALL_ROUNDS = 5

_TOOLS_BY_NAME = {tool.__name__: tool for tool in AVAILABLE_TOOLS}
_TOOL_SCHEMAS = [function_to_openai_schema(tool) for tool in AVAILABLE_TOOLS]


def _run_tool(name: str, arguments_json: str) -> str:
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"Error: tool '{name}' tidak dikenali."

    try:
        kwargs = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return f"Error: argumen tool '{name}' bukan JSON valid."

    try:
        return str(tool(**kwargs))
    except Exception as exc:  # tool bisa error karena input aneh dari model -- jangan sampai
        # menggagalkan seluruh request, cukup laporkan balik ke model sebagai hasil tool.
        return f"Error saat menjalankan tool '{name}': {exc}"


def _accumulate_usage(total: TokenUsage, usage) -> None:
    if usage is None:
        return
    total.prompt_tokens = (total.prompt_tokens or 0) + (getattr(usage, "prompt_tokens", 0) or 0)
    total.output_tokens = (total.output_tokens or 0) + (getattr(usage, "completion_tokens", 0) or 0)
    total.total_tokens = (total.total_tokens or 0) + (getattr(usage, "total_tokens", 0) or 0)


class OpenAICompatibleProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        provider_name: str = "openai",
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, default_headers=default_headers
        )
        self._model = model
        self._provider_name = provider_name

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
        chat_messages: list[dict] = []
        if system_instruction:
            chat_messages.append({"role": "system", "content": system_instruction})
        if response_schema is not None:
            chat_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Jawab HANYA dengan JSON valid yang cocok dengan schema berikut, "
                        "tanpa markdown/backticks/teks lain:\n"
                        f"{json.dumps(response_schema.model_json_schema())}"
                    ),
                }
            )
        chat_messages.extend(messages)

        tools = _TOOL_SCHEMAS if use_tools else None
        tools_called: list[str] = []
        total_usage = TokenUsage(prompt_tokens=0, output_tokens=0, total_tokens=0)
        text = ""

        start = time.perf_counter()
        try:
            choice = None
            for _ in range(MAX_TOOL_CALL_ROUNDS):
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=cast("Iterable[ChatCompletionMessageParam]", chat_messages),
                    tools=cast("Iterable[ChatCompletionToolUnionParam]", tools)
                    if tools is not None
                    else omit,
                )
                choice = response.choices[0]
                _accumulate_usage(total_usage, response.usage)

                pending_tool_calls = choice.message.tool_calls or []
                if not pending_tool_calls:
                    text = choice.message.content or ""
                    break

                chat_messages.append(choice.message.model_dump(exclude_none=True))
                for call in pending_tool_calls:
                    # Kita cuma pernah mengirim tool berjenis "function" lewat
                    # `_TOOL_SCHEMAS` (lihat tool_schema.py), jadi `call.function`
                    # semestinya selalu ada -- tapi tipe SDK-nya union dengan
                    # varian "custom tool call" yang tidak punya `.function`,
                    # jadi diakses defensif, bukan diasumsikan.
                    function_call = getattr(call, "function", None)
                    if function_call is None:
                        continue
                    result = _run_tool(function_call.name, function_call.arguments)
                    tools_called.append(function_call.name)
                    chat_messages.append(
                        {"role": "tool", "tool_call_id": call.id, "content": result}
                    )
            else:
                # Habis MAX_TOOL_CALL_ROUNDS masih minta tool -- ambil apa adanya
                # daripada loop lebih jauh dan memboroskan panggilan.
                text = choice.message.content or "" if choice else ""
        except OpenAIAPIError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log_event(
                logger,
                "llm_call",
                provider=self._provider_name,
                model=self._model,
                duration_ms=duration_ms,
                success=False,
                error=str(exc),
            )
            status_code = getattr(exc, "status_code", None)
            retryable = status_code is None or status_code in (429, 500, 502, 503, 504)
            raise ProviderError(str(exc), retryable=retryable) from exc

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            logger,
            "llm_call",
            provider=self._provider_name,
            model=self._model,
            duration_ms=duration_ms,
            success=True,
            tools_called=tools_called,
            prompt_tokens=total_usage.prompt_tokens,
            output_tokens=total_usage.output_tokens,
            total_tokens=total_usage.total_tokens,
        )

        parsed = None
        if response_schema is not None:
            try:
                parsed = response_schema.model_validate_json(text)
            except ValidationError:
                parsed = None

        return GenerationResult(
            text=text, parsed=parsed, usage=total_usage, tools_called=tools_called
        )
