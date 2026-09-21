import pytest

from app.services.llm_providers.base import GenerationResult, ProviderError
from app.services.llm_providers.fallback import FallbackProvider


class FakeProvider:
    def __init__(self, model: str, result: GenerationResult | None = None, error=None):
        self.model = model
        self.result = result
        self.error = error
        self.call_count = 0

    async def generate(
        self,
        messages,
        *,
        system_instruction=None,
        response_schema=None,
        use_tools=False,
    ) -> GenerationResult:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


async def test_uses_first_provider_when_it_succeeds():
    healthy = FakeProvider("healthy-model", result=GenerationResult(text="halo"))
    never_called = FakeProvider("backup-model", result=GenerationResult(text="tidak dipakai"))
    fallback = FallbackProvider([healthy, never_called])

    result = await fallback.generate([{"role": "user", "content": "hai"}])

    assert result.text == "halo"
    assert never_called.call_count == 0
    assert fallback.model == "healthy-model"


async def test_falls_back_to_next_provider_when_first_fails():
    broken = FakeProvider("broken-model", error=ProviderError("kuota habis", retryable=True))
    healthy = FakeProvider("healthy-model", result=GenerationResult(text="balasan cadangan"))
    fallback = FallbackProvider([broken, healthy])

    result = await fallback.generate([{"role": "user", "content": "hai"}])

    assert result.text == "balasan cadangan"
    assert broken.call_count == 1
    assert fallback.model == "healthy-model"


async def test_falls_back_even_on_non_retryable_errors():
    """FallbackProvider bukan retry -- SEMUA ProviderError jadi alasan pindah
    provider, termasuk yang non-retryable (mis. model 404), karena bagi
    failover itu tetap berarti 'provider ini tidak bisa dipakai sekarang'."""
    broken = FakeProvider("broken-model", error=ProviderError("model tidak ada", retryable=False))
    healthy = FakeProvider("healthy-model", result=GenerationResult(text="balasan cadangan"))
    fallback = FallbackProvider([broken, healthy])

    result = await fallback.generate([{"role": "user", "content": "hai"}])

    assert result.text == "balasan cadangan"


async def test_raises_last_error_when_all_providers_fail():
    first = FakeProvider("model-a", error=ProviderError("gagal A", retryable=False))
    second = FakeProvider("model-b", error=ProviderError("gagal B", retryable=True))
    fallback = FallbackProvider([first, second])

    with pytest.raises(ProviderError) as exc_info:
        await fallback.generate([{"role": "user", "content": "hai"}])

    assert str(exc_info.value) == "gagal B"
    assert exc_info.value.retryable is True


async def test_model_property_reflects_currently_active_provider():
    broken = FakeProvider("broken-model", error=ProviderError("kuota habis", retryable=True))
    healthy = FakeProvider("healthy-model", result=GenerationResult(text="ok"))
    fallback = FallbackProvider([broken, healthy])

    assert fallback.model == "broken-model"  # sebelum request apapun, default ke yang pertama

    await fallback.generate([{"role": "user", "content": "hai"}])

    assert fallback.model == "healthy-model"


def test_raises_immediately_when_constructed_with_empty_list():
    with pytest.raises(ValueError, match="minimal 1 provider"):
        FallbackProvider([])
