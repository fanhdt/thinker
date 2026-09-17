"""Boundary generik untuk provider LLM (Bagian 18 master prompt: Model-Agnostic
Architecture).

Semua yang provider-SPESIFIK (bentuk request, cara structured output diminta,
cara tool-calling dijalankan, cara error dipetakan) hidup di implementasi
`LLMProvider` masing-masing (`gemini.py`, `openai_compatible.py`). Kode
bisnis di `app/services/llm.py` (prompt, schema, alur reflection) HANYA
boleh bicara lewat tipe-tipe generik di file ini -- tidak boleh import
`google.genai` atau `openai` sama sekali.
"""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel


@dataclass
class TokenUsage:
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class GenerationResult:
    """Hasil generik dari satu panggilan LLM, provider apapun itu."""

    text: str
    parsed: BaseModel | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    tools_called: list[str] = field(default_factory=list)


class ProviderError(Exception):
    """Pengganti generik untuk error provider apapun (dulu `APIError` Gemini
    bocor sampai ke `LLMService`). `retryable=True` untuk error yang sifatnya
    sementara (rate limit, service unavailable) -- lihat masing-masing
    provider untuk pemetaan kode errornya.
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    """Kontrak yang harus dipenuhi provider apapun. `LLMService` di
    `app/services/llm.py` cuma bergantung ke interface ini, tidak pernah ke
    implementasi konkretnya -- persis "Idealnya cukup mengganti configuration
    untuk berpindah model" di master prompt.
    """

    @property
    def model(self) -> str: ...

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        use_tools: bool = False,
    ) -> GenerationResult:
        """`messages`: list of {"role": "user"|"assistant", "content": str},
        urutan chronological, TANPA role "system" (pakai `system_instruction`
        terpisah -- beberapa provider punya slot native untuk ini, jadi
        jangan dipaksa masuk ke `messages`).

        `response_schema`: kalau diisi, provider diminta mengembalikan JSON
        sesuai schema Pydantic ini; hasilnya divalidasi dan ditaruh di
        `GenerationResult.parsed` (None kalau provider gagal mengikuti
        schema -- pemanggil HARUS menangani kasus ini, jangan diasumsikan
        selalu berhasil).

        `use_tools`: kalau True, provider boleh memanggil tools dari
        `app.services.tools.registry.AVAILABLE_TOOLS` sebanyak yang
        diperlukan (dibatasi internal oleh provider) sebelum mengembalikan
        jawaban akhir.
        """
        ...