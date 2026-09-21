"""Menerjemahkan config (`settings.llm_provider` / `llm_provider_chain`)
menjadi instance provider konkret. Menambah provider OpenAI-compatible baru
cukup tambah satu cabang di `_build_provider_instances` -- tidak perlu
menyentuh `LLMService` maupun kode bisnis lainnya sama sekali.
"""

from app.core.config import settings
from app.services.llm_providers.base import LLMProvider
from app.services.llm_providers.fallback import FallbackProvider
from app.services.llm_providers.gemini import GeminiProvider
from app.services.llm_providers.openai_compatible import OpenAICompatibleProvider

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _require(value: str | None, provider: str, field_name: str) -> str:
    if not value:
        raise ValueError(
            f"llm_provider='{provider}' tapi '{field_name}' belum diisi di .env/config."
        )
    return value


def _split_keys(raw_keys: str) -> list[str]:
    """Satu field API key boleh diisi beberapa key dipisah koma, mis. buat
    2 project Gemini gratis berbeda: `GEMINI_API_KEY=key-project-1,key-project-2`.
    Tiap key jadi instance provider terpisah dalam rantai failover -- kalau
    key pertama kena limit kuota, otomatis coba key berikutnya SEBELUM
    pindah ke provider lain.
    """
    keys = [key.strip() for key in raw_keys.split(",") if key.strip()]
    if not keys:
        raise ValueError("API key diisi tapi tidak ada key yang valid setelah dipisah koma.")
    return keys


def _build_provider_instances(provider: str) -> list[LLMProvider]:
    """Bangun SATU ATAU LEBIH instance provider untuk satu nama provider --
    lebih dari satu kalau field API key-nya berisi beberapa key dipisah koma.
    """
    if provider == "gemini":
        api_key = _require(settings.gemini_api_key, provider, "gemini_api_key")
        return [
            GeminiProvider(api_key=key, model=settings.gemini_model) for key in _split_keys(api_key)
        ]

    if provider == "openai":
        api_key = _require(settings.openai_api_key, provider, "openai_api_key")
        return [
            OpenAICompatibleProvider(
                api_key=key, model=settings.openai_model, provider_name="openai"
            )
            for key in _split_keys(api_key)
        ]

    if provider == "groq":
        api_key = _require(settings.groq_api_key, provider, "groq_api_key")
        return [
            OpenAICompatibleProvider(
                api_key=key,
                model=settings.groq_model,
                base_url=_GROQ_BASE_URL,
                provider_name="groq",
            )
            for key in _split_keys(api_key)
        ]

    if provider == "deepseek":
        api_key = _require(settings.deepseek_api_key, provider, "deepseek_api_key")
        return [
            OpenAICompatibleProvider(
                api_key=key,
                model=settings.deepseek_model,
                base_url=_DEEPSEEK_BASE_URL,
                provider_name="deepseek",
            )
            for key in _split_keys(api_key)
        ]

    if provider == "openrouter":
        api_key = _require(settings.openrouter_api_key, provider, "openrouter_api_key")
        # HTTP-Referer/X-Title murni buat ranking di dashboard OpenRouter,
        # bukan syarat autentikasi -- aman diisi None (dihapus AsyncOpenAI
        # kalau None, tidak dikirim sebagai header kosong). Sama untuk
        # semua instance kalau ada beberapa key OpenRouter.
        headers = {
            k: v
            for k, v in {
                "HTTP-Referer": settings.openrouter_site_url,
                "X-Title": settings.openrouter_app_name,
            }.items()
            if v
        }
        return [
            OpenAICompatibleProvider(
                api_key=key,
                model=settings.openrouter_model,
                base_url=_OPENROUTER_BASE_URL,
                provider_name="openrouter",
                default_headers=headers or None,
            )
            for key in _split_keys(api_key)
        ]

    raise ValueError(
        f"llm_provider tidak dikenali: '{provider}'. "
        "Pilihan: gemini, openai, groq, deepseek, openrouter."
    )


def _build_from_config(chain: str | None, single: str | None) -> LLMProvider:
    if chain:
        names = [name.strip() for name in chain.split(",") if name.strip()]
        if not names:
            raise ValueError("Rantai provider diisi tapi tidak ada nama provider yang valid.")
        instances: list[LLMProvider] = []
        for name in names:
            instances.extend(_build_provider_instances(name))
        return FallbackProvider(instances)

    instances = _build_provider_instances(single or settings.llm_provider)
    if len(instances) == 1:
        return instances[0]
    # Satu nama provider, tapi beberapa key -- tetap bungkus FallbackProvider
    # supaya failover key-ke-key jalan walau LLM_PROVIDER_CHAIN tidak dipakai.
    return FallbackProvider(instances)


def build_provider() -> LLMProvider:
    """Provider default/global -- dipakai kalau tidak ada override per-tier
    (lihat `build_simple_provider`/`build_planner_provider`)."""
    return _build_from_config(settings.llm_provider_chain, settings.llm_provider)


def build_simple_provider() -> LLMProvider:
    """Provider untuk task RINGAN: chat biasa, klasifikasi routing
    (`classify_and_plan`), ekstraksi memori (`extract_fact`). Kalau
    `LLM_PROVIDER_SIMPLE(_CHAIN)` tidak diisi, jatuh kembali ke provider
    default -- tidak konfigurasi apa pun = perilaku identik seperti
    sebelum tiering ada.
    """
    if settings.llm_provider_simple_chain or settings.llm_provider_simple:
        return _build_from_config(settings.llm_provider_simple_chain, settings.llm_provider_simple)
    return build_provider()


def build_planner_provider() -> LLMProvider:
    """Provider untuk task PLANNER: `create_plan` dan `execute_and_evaluate`
    -- ini yang paling berat reasoning-nya (mengerjakan + menilai sendiri
    hasilnya, kadang pakai tools). Sama, jatuh kembali ke provider default
    kalau tidak dikonfigurasi khusus.
    """
    if settings.llm_provider_planner_chain or settings.llm_provider_planner:
        return _build_from_config(
            settings.llm_provider_planner_chain, settings.llm_provider_planner
        )
    return build_provider()
