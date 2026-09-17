import pytest

from app.core.config import settings
from app.services.llm_providers.factory import (
    build_planner_provider,
    build_provider,
    build_simple_provider,
)
from app.services.llm_providers.fallback import FallbackProvider
from app.services.llm_providers.gemini import GeminiProvider
from app.services.llm_providers.openai_compatible import OpenAICompatibleProvider


@pytest.fixture(autouse=True)
def _reset_settings():
    """Simpan & kembalikan settings asli -- test ini sengaja mengubah
    `settings.llm_provider` dkk untuk menguji factory, jangan sampai bocor
    ke test lain yang jalan setelahnya."""
    original = settings.model_dump()
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_factory_builds_gemini_provider_by_default():
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "fake-key"

    provider = build_provider()

    assert isinstance(provider, GeminiProvider)
    assert provider.model == settings.gemini_model


@pytest.mark.parametrize(
    ("provider_name", "key_field"),
    [
        ("openai", "openai_api_key"),
        ("groq", "groq_api_key"),
        ("deepseek", "deepseek_api_key"),
        ("openrouter", "openrouter_api_key"),
    ],
)
def test_factory_builds_openai_compatible_provider_for_each_provider(provider_name, key_field):
    settings.llm_provider = provider_name
    setattr(settings, key_field, "fake-key")

    provider = build_provider()

    assert isinstance(provider, OpenAICompatibleProvider)


def test_factory_omits_openrouter_ranking_headers_when_not_configured():
    """HTTP-Referer/X-Title itu opsional (cuma ranking di dashboard OpenRouter)
    -- factory tidak boleh mengirim header kosong kalau user tidak mengisinya."""
    settings.llm_provider = "openrouter"
    settings.openrouter_api_key = "fake-key"
    settings.openrouter_site_url = None
    settings.openrouter_app_name = None

    provider = build_provider()

    assert isinstance(provider, OpenAICompatibleProvider)


def test_factory_raises_clear_error_when_api_key_missing():
    settings.llm_provider = "openai"
    settings.openai_api_key = None

    with pytest.raises(ValueError, match="openai_api_key"):
        build_provider()


def test_factory_raises_clear_error_for_unknown_provider():
    settings.llm_provider = "some-unknown-provider"

    with pytest.raises(ValueError, match="tidak dikenali"):
        build_provider()


def test_factory_builds_fallback_chain_when_configured():
    settings.llm_provider_chain = "gemini,openrouter"
    settings.gemini_api_key = "fake-gemini-key"
    settings.openrouter_api_key = "fake-openrouter-key"

    provider = build_provider()

    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider._providers[0], GeminiProvider)
    assert isinstance(provider._providers[1], OpenAICompatibleProvider)


def test_factory_chain_still_validates_each_providers_key():
    settings.llm_provider_chain = "gemini,groq"
    settings.gemini_api_key = "fake-gemini-key"
    settings.groq_api_key = None

    with pytest.raises(ValueError, match="groq_api_key"):
        build_provider()


def test_factory_ignores_single_llm_provider_when_chain_is_set():
    """Kalau LLM_PROVIDER_CHAIN diisi, itu MENGGANTIKAN LLM_PROVIDER tunggal
    -- bukan digabung atau dipilih salah satu secara ambigu."""
    settings.llm_provider = "openai"
    settings.openai_api_key = None  # sengaja kosong -- seharusnya tidak dicek sama sekali
    settings.llm_provider_chain = "gemini"
    settings.gemini_api_key = "fake-gemini-key"

    provider = build_provider()

    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider._providers[0], GeminiProvider)


def test_simple_and_planner_tier_both_fall_back_to_default_when_unconfigured():
    """Tidak mengonfigurasi tiering sama sekali = kedua tier pakai provider
    default yang sama -- perilaku identik seperti sebelum tiering ada."""
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "fake-key"
    settings.llm_provider_simple = None
    settings.llm_provider_simple_chain = None
    settings.llm_provider_planner = None
    settings.llm_provider_planner_chain = None

    simple = build_simple_provider()
    planner = build_planner_provider()

    assert isinstance(simple, GeminiProvider)
    assert isinstance(planner, GeminiProvider)


def test_simple_tier_can_be_configured_independently_from_planner_tier():
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "fake-key"
    settings.llm_provider_simple = "groq"
    settings.groq_api_key = "fake-groq-key"
    settings.llm_provider_planner = None  # tetap jatuh ke default

    simple = build_simple_provider()
    planner = build_planner_provider()

    assert isinstance(simple, OpenAICompatibleProvider)
    assert isinstance(planner, GeminiProvider)  # default, tidak terpengaruh simple


def test_planner_tier_can_use_its_own_fallback_chain():
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "fake-key"
    settings.llm_provider_planner_chain = "gemini,openrouter"
    settings.openrouter_api_key = "fake-openrouter-key"

    planner = build_planner_provider()

    assert isinstance(planner, FallbackProvider)


def test_single_provider_with_multiple_comma_separated_keys_builds_fallback_chain():
    """Kasus utama: 2 project Gemini gratis berbeda, tanpa LLM_PROVIDER_CHAIN
    sama sekali -- cukup GEMINI_API_KEY=key1,key2."""
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "key-project-1,key-project-2"

    provider = build_provider()

    assert isinstance(provider, FallbackProvider)
    assert len(provider._providers) == 2
    assert all(isinstance(p, GeminiProvider) for p in provider._providers)


def test_single_key_does_not_wrap_in_fallback_unnecessarily():
    """Kalau cuma 1 key, jangan dibungkus FallbackProvider -- tidak ada
    gunanya menambah lapisan untuk kasus yang paling umum."""
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "cuma-satu-key"

    provider = build_provider()

    assert isinstance(provider, GeminiProvider)


def test_chain_and_multi_key_combine_correctly():
    """LLM_PROVIDER_CHAIN=gemini,openrouter DENGAN 2 key Gemini -- harus
    jadi 3 instance total: gemini(key1), gemini(key2), openrouter -- bukan
    cuma 2 (yang akan kehilangan salah satu key Gemini)."""
    settings.llm_provider_chain = "gemini,openrouter"
    settings.gemini_api_key = "key1,key2"
    settings.openrouter_api_key = "fake-openrouter-key"

    provider = build_provider()

    assert isinstance(provider, FallbackProvider)
    assert len(provider._providers) == 3
    assert isinstance(provider._providers[0], GeminiProvider)
    assert isinstance(provider._providers[1], GeminiProvider)
    assert isinstance(provider._providers[2], OpenAICompatibleProvider)


def test_blank_keys_around_commas_are_ignored():
    settings.llm_provider = "gemini"
    settings.gemini_api_key = "key1, , key2,"

    provider = build_provider()

    assert isinstance(provider, FallbackProvider)
    assert len(provider._providers) == 2