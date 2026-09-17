import pytest

from app.services.llm import LLMService, LLMServiceError, MessagePlan, TaskOutcome
from app.services.llm_providers.base import GenerationResult, ProviderError


class FakeProvider:
    """Fake generik yang mengimplementasikan `LLMProvider` Protocol -- dipakai
    untuk menguji LOGIKA BISNIS di `LLMService` (susunan prompt, penanganan
    parsing gagal, dst) tanpa peduli provider konkret mana yang sebenarnya
    dipakai. Tes untuk perilaku Gemini-spesifik ada di test_gemini_provider.py.
    """

    def __init__(self, result: GenerationResult | None = None, error: ProviderError | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []
        self.model = "fake-model"

    async def generate(
        self,
        messages,
        *,
        system_instruction=None,
        response_schema=None,
        use_tools=False,
    ) -> GenerationResult:
        self.calls.append(
            {
                "messages": messages,
                "system_instruction": system_instruction,
                "response_schema": response_schema,
                "use_tools": use_tools,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.mark.parametrize("retryable", [True, False])
async def test_chat_propagates_provider_retryable_flag(retryable):
    """LLMServiceError.retryable harus mengikuti apa yang provider bilang --
    LLMService tidak lagi menentukan sendiri kode error mana yang retryable
    (itu tanggung jawab provider), cuma meneruskan.
    """
    provider = FakeProvider(error=ProviderError("boom", retryable=retryable))
    service = LLMService(provider=provider)

    with pytest.raises(LLMServiceError) as exc_info:
        await service.chat("halo")

    assert exc_info.value.retryable is retryable


async def test_chat_raises_when_provider_returns_empty_text():
    provider = FakeProvider(result=GenerationResult(text=""))
    service = LLMService(provider=provider)

    with pytest.raises(LLMServiceError):
        await service.chat("halo")


async def test_chat_with_history_requests_tools():
    """chat_with_history harus selalu minta tools (kalkulator/datetime/web
    search tersedia untuk chat biasa, bukan cuma di planner)."""
    provider = FakeProvider(result=GenerationResult(text="balasan"))
    service = LLMService(provider=provider)

    await service.chat_with_history(
        [{"role": "user", "content": "halo"}], system_instruction="konteks personalisasi"
    )

    assert provider.calls[0]["use_tools"] is True
    assert provider.calls[0]["system_instruction"] == "konteks personalisasi"


async def test_classify_and_plan_falls_back_safely_when_parsing_fails():
    """Kalau provider gagal mengembalikan MessagePlan yang valid (mis. model
    lain yang kurang patuh ke response_schema), LLMService tidak boleh
    meledak -- fallback ke needs_planning=False, bukan crash."""
    provider = FakeProvider(result=GenerationResult(text="bukan json valid", parsed=None))
    service = LLMService(provider=provider)

    result = await service.classify_and_plan("Rencanakan liburan")

    assert result == MessagePlan(needs_planning=False, tasks=[])


async def test_execute_and_evaluate_falls_back_to_is_correct_true_on_parse_failure():
    """Sama seperti classify_and_plan: kalau TaskOutcome gagal di-parse,
    fallback ke is_correct=True dengan teks mentah sebagai hasil -- bukan crash,
    dan bukan diam-diam kehilangan apa yang model tulis."""
    provider = FakeProvider(result=GenerationResult(text="ini hasil mentah", parsed=None))
    service = LLMService(provider=provider)

    outcome = await service.execute_and_evaluate("task apapun", "")

    assert outcome == TaskOutcome(result="ini hasil mentah", is_correct=True, feedback="")


async def test_execute_and_evaluate_requests_tools():
    provider = FakeProvider(
        result=GenerationResult(
            text="{}", parsed=TaskOutcome(result="hasil", is_correct=True, feedback="")
        )
    )
    service = LLMService(provider=provider)

    await service.execute_and_evaluate("task apapun", "")

    assert provider.calls[0]["use_tools"] is True


async def test_model_property_reflects_active_provider_model():
    provider = FakeProvider()
    provider.model = "some-provider/some-model"
    service = LLMService(provider=provider)

    assert service.model == "some-provider/some-model"


async def test_simple_tier_methods_use_simple_provider_not_planner():
    """chat, chat_with_history, extract_fact, dan classify_and_plan harus
    lewat provider tier SIMPLE -- ini yang dipanggil di setiap pesan user,
    jadi harus tetap murah/cepat, bukan provider planner yang lebih mahal."""
    simple = FakeProvider(result=GenerationResult(text="balasan"))
    planner = FakeProvider(
        result=GenerationResult(text="tidak boleh terpanggil untuk tier simple")
    )
    service = LLMService(simple_provider=simple, planner_provider=planner)

    await service.chat("halo")
    await service.chat_with_history([{"role": "user", "content": "halo"}])
    await service.classify_and_plan("pesan apapun")

    assert len(simple.calls) == 3
    assert len(planner.calls) == 0


async def test_planner_tier_methods_use_planner_provider_not_simple():
    """create_plan dan execute_and_evaluate -- pekerjaan paling berat
    reasoning-nya -- harus lewat provider tier PLANNER, bukan simple."""
    simple = FakeProvider(result=GenerationResult(text="tidak boleh terpanggil untuk planner"))
    planner = FakeProvider(
        result=GenerationResult(
            text="{}", parsed=TaskOutcome(result="hasil", is_correct=True, feedback="")
        )
    )
    service = LLMService(simple_provider=simple, planner_provider=planner)

    await service.execute_and_evaluate("task apapun", "")

    assert len(planner.calls) == 1
    assert len(simple.calls) == 0


async def test_model_and_planner_model_report_their_own_tier():
    simple = FakeProvider()
    simple.model = "cheap-model"
    planner = FakeProvider()
    planner.model = "strong-model"
    service = LLMService(simple_provider=simple, planner_provider=planner)

    assert service.model == "cheap-model"
    assert service.planner_model == "strong-model"