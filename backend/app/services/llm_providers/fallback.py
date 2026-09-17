"""Rantai failover antar provider (Bagian 18 lanjutan: resiliency).

Kalau provider pertama gagal (kuota habis, saldo habis, model tidak
tersedia, dst), otomatis coba provider berikutnya dalam daftar -- bukan
langsung menggagalkan seluruh request ke user.

PENTING -- ini BUKAN retry. Retry berarti mengulang request yang SAMA ke
provider yang SAMA (itu urusan pemanggil/`retryable` flag di `ProviderError`).
`FallbackProvider` murni "kalau provider ini lagi bermasalah, pindah ke
lain", jadi SEMUA `ProviderError` jadi alasan pindah, terlepas dari
`retryable`-nya -- termasuk error yang bukan retryable seperti model 404
(karena bagi failover, itu tetap berarti "provider ini tidak bisa dipakai
sekarang").
"""

import logging

from pydantic import BaseModel

from app.core.logging_config import log_event
from app.services.llm_providers.base import GenerationResult, LLMProvider, ProviderError

logger = logging.getLogger(__name__)


class FallbackProvider:
    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackProvider butuh minimal 1 provider dalam rantainya")
        self._providers = providers
        # Provider yang berhasil melayani request TERAKHIR -- dipakai property
        # `model` supaya mencerminkan provider yang benar-benar sedang aktif,
        # bukan selalu yang pertama di daftar.
        self._active_index = 0

    @property
    def model(self) -> str:
        return self._providers[self._active_index].model

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        use_tools: bool = False,
    ) -> GenerationResult:
        last_error: ProviderError | None = None

        for index, provider in enumerate(self._providers):
            try:
                result = await provider.generate(
                    messages,
                    system_instruction=system_instruction,
                    response_schema=response_schema,
                    use_tools=use_tools,
                )
            except ProviderError as exc:
                last_error = exc
                log_event(
                    logger,
                    "provider_fallback",
                    failed_provider=provider.model,
                    position=index,
                    total_providers=len(self._providers),
                    error=str(exc),
                    has_next=index + 1 < len(self._providers),
                )
                continue

            if index != self._active_index:
                log_event(
                    logger,
                    "provider_fallback_succeeded",
                    provider=provider.model,
                    position=index,
                )
            self._active_index = index
            return result

        # Semua provider di rantai gagal -- lempar error TERAKHIR (bukan yang
        # pertama), karena itu yang paling relevan dengan kondisi saat ini.
        assert last_error is not None
        raise last_error